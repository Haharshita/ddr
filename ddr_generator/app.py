import streamlit as st
import os
import fitz  # PyMuPDF
import json
from pydantic import BaseModel, Field
from typing import List, Optional
from google import genai
from google.genai import types
import groq
from pdf_builder import build_ddr_pdf
from dotenv import load_dotenv

# ── Load .env ──
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ── Persistent directories ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, "extracted_images")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# Pydantic schemas — DDR structure
# ─────────────────────────────────────────────

class ImageRef(BaseModel):
    image_id: str = Field(description="Exact image filename from the provided list. 'Image Not Available' if none.")
    caption: str = Field(description="Short caption for the image.")

class AreaObservation(BaseModel):
    area_name: str = Field(description="Area/location name e.g. 'Ceiling - Hall (Ground Floor)'")
    inspection_findings: str = Field(description="Findings from Inspection Report. 'Not Available' if none.")
    thermal_findings: str = Field(description="Thermal readings/observations. 'Not Available' if none.")
    relevant_images: List[ImageRef] = Field(description="Images relevant to this area from the provided list.")

class SeverityAssessment(BaseModel):
    level: str = Field(description="Critical / High / Medium / Low")
    reasoning: str = Field(description="Why this severity was chosen")

class DDRReport(BaseModel):
    property_issue_summary: str = Field(description="Executive summary of main issues from both reports")
    area_wise_observations: List[AreaObservation] = Field(description="Observations grouped by area, merging both reports")
    probable_root_cause: str = Field(description="Likely root cause(s)")
    severity_assessment: SeverityAssessment
    recommended_actions: List[str] = Field(description="Recommended next steps/repairs")
    additional_notes: str = Field(description="Other relevant info. 'Not Available' if none.")
    missing_or_unclear_information: str = Field(description="Missing/conflicting info. 'Not Available' if consistent.")


# ─────────────────────────────────────────────
# PDF extraction
# ─────────────────────────────────────────────

def extract_from_pdf(pdf_bytes: bytes, label: str):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = f"\n{'='*50}\n{label.upper()} REPORT\n{'='*50}\n"
    images_meta = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = page.get_text()
        # Clean text: remove multiple newlines and extra spaces to save tokens
        page_text = " ".join(page_text.split())
        full_text += f"\n--- Page {page_num + 1} ---\n{page_text}"

        for img_idx, img_info in enumerate(page.get_images(full=True)):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue
            img_bytes = base_image["image"]
            img_ext = base_image["ext"]

            # Skip only tiny icon-sized images by checking pixel dimensions
            img_w = base_image.get("width", 999)
            img_h = base_image.get("height", 999)
            if img_w < 50 or img_h < 50:
                continue  # skip tiny icons/bullets

            filename = f"{label}_p{page_num+1}_i{img_idx+1}.{img_ext}"
            filepath = os.path.join(IMAGES_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(img_bytes)

            snippet = page_text[:200].replace("\n", " ").strip()
            images_meta.append({
                "source": label, "page": page_num + 1,
                "filename": filename, "filepath": filepath,
                "page_context": snippet,
            })
    return full_text, images_meta


# ─────────────────────────────────────────────
# LLM call
# ─────────────────────────────────────────────

def generate_ddr(provider: str, api_key: str, text: str, image_list_str: str) -> dict:
    prompt = f"""You are an expert property inspection analyst creating a Detailed Diagnostic Report (DDR).

You are given two raw documents: an Inspection Report and a Thermal Report for the same property.
Your job is to merge ALL findings into a comprehensive, highly detailed DDR.

CRITICAL RULES:
1. Do NOT invent or hallucinate ANY facts not present in the source documents.
2. Merge information from both reports logically. Avoid duplicate points.
3. If information conflicts between the two reports, explicitly state the conflict.
4. If expected information is missing, write "Not Available".
5. Use simple, client-friendly language.
6. Map images using EXACT filenames from the IMAGE LIST below.
7. Return the final output strictly as a valid JSON object.

DETAIL REQUIREMENTS - THIS IS VERY IMPORTANT:
- property_issue_summary: Write a COMPREHENSIVE executive summary (at least 200 words). Cover ALL areas affected (bathrooms, balcony, terrace, external walls, etc.), mention specific issues like dampness, cracks, efflorescence, seepage, hollowness, vegetation growth. Include the property address and inspection details if available.
- area_wise_observations: Create a SEPARATE observation for EACH distinct area mentioned in the reports (e.g., Hall Ceiling, Bedroom Skirting, Common Bathroom, Master Bedroom, Balcony, Terrace, External Walls, Staircase). Each observation must include specific details like moisture readings, temperature data, crack widths, condition ratings (Good/Moderate/Poor), and specific materials/products mentioned.
- probable_root_cause: Write a DETAILED analysis (at least 150 words) explaining the chain of causation - how gaps in tile joints lead to capillary action, how external wall cracks allow water ingress, how terrace damage causes ceiling leakage, etc.
- severity_assessment: Provide thorough reasoning covering structural safety, water damage progression, and urgency.
- recommended_actions: List AT LEAST 6 specific actionable recommendations. Include specific products (e.g., Dr. Fixit URP), techniques (V-groove cutting, polymer modified mortar), and procedures mentioned in the source documents.
- additional_notes: Include any structural warnings, delayed action consequences, warranty information, or special precautions from the reports.
- missing_or_unclear_information: List any data gaps, unclear readings, or areas that could not be fully assessed.

--- EXPECTED JSON STRUCTURE ---
You MUST return a JSON object with this EXACT structure:
{{
  "property_issue_summary": "...",
  "area_wise_observations": [
    {{
      "area_name": "...",
      "inspection_findings": "...",
      "thermal_findings": "...",
      "relevant_images": [{{ "image_id": "...", "caption": "..." }}]
    }}
  ],
  "probable_root_cause": "...",
  "severity_assessment": {{ "level": "Critical/High/Medium/Low", "reasoning": "..." }},
  "recommended_actions": ["...", "..."],
  "additional_notes": "...",
  "missing_or_unclear_information": "..."
}}

--- DOCUMENTS ---
{text}

--- IMAGE LIST ---
{image_list_str}

Respond only with the JSON.
"""
    if provider == "Gemini (Google)":
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-1.5-flash", contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DDRReport, temperature=0.3,
            ),
        )
        return json.loads(response.text)
    else:
        # Groq provider - Truncate prompt to ~7.5k tokens (approx 30k chars) 
        # to stay within strict free tier TPM limits (12k total)
        if len(prompt) > 30000:
            prompt = prompt[:30000] + "\n\n[TEXT TRUNCATED DUE TO GROQ LIMITS]...\n\nRespond with the JSON for the available text."
        
        client = groq.Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        return json.loads(response.choices[0].message.content)


# ─────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────

st.set_page_config(page_title="AI DDR Report Generator", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, p, span, li, td, th, label, input, textarea, button, h1, h2, h3, h4, h5, h6, div.stMarkdown {
    font-family: 'Inter', sans-serif;
}
.main .block-container { max-width: 1100px; padding-top: 2rem; }
h1 { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
div[data-testid="stSidebar"] { background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%); }
div[data-testid="stSidebar"] p, div[data-testid="stSidebar"] span, div[data-testid="stSidebar"] label,
div[data-testid="stSidebar"] h1, div[data-testid="stSidebar"] h2, div[data-testid="stSidebar"] h3 {
    color: #e0e0e0 !important;
}
</style>
""", unsafe_allow_html=True)

st.title("AI DDR Report Generator")
st.caption("Upload Inspection & Thermal reports - Get a professional DDR PDF, matching industry format.")

with st.sidebar:
    st.header("Configuration")
    provider = st.selectbox("AI Provider", ["Gemini (Google)", "Llama 3 (Groq)"], help="Gemini is default. Groq is faster and good for bypassing limits.")
    
    if provider == "Gemini (Google)":
        if GEMINI_API_KEY:
            st.success("Gemini API Key loaded")
            api_key = GEMINI_API_KEY
        else:
            api_key = st.text_input("Gemini API Key", type="password", help="Free key from aistudio.google.com")
    else:
        if GROQ_API_KEY:
            st.success("Groq API Key loaded")
            api_key = GROQ_API_KEY
        else:
            api_key = st.text_input("Groq API Key", type="password", help="Free key from console.groq.com")
            
    st.markdown("---")
    st.header("Upload Documents")
    inspection_file = st.file_uploader("Inspection Report (PDF)", type=["pdf"], key="insp")
    thermal_file = st.file_uploader("Thermal Report (PDF)", type=["pdf"], key="therm")
    st.markdown("---")
    generate_btn = st.button("Generate DDR Report", type="primary", use_container_width=True)

def normalize_report_data(data: dict) -> dict:
    """Fix common AI response variations to match schema."""
    if not isinstance(data, dict):
        return {}
    
    # Map synonyms for top-level keys
    key_map = {
        "summary": "property_issue_summary",
        "observations": "area_wise_observations",
        "root_cause": "probable_root_cause",
        "severity": "severity_assessment",
        "recommendations": "recommended_actions",
        "notes": "additional_notes",
        "missing_info": "missing_or_unclear_information"
    }
    for old, new in key_map.items():
        if old in data and new not in data:
            data[new] = data.pop(old)

    # Normalize area observations
    if "area_wise_observations" in data and isinstance(data["area_wise_observations"], list):
        normalized_obs = []
        for obs in data["area_wise_observations"]:
            if isinstance(obs, dict):
                # Map area observation synonyms
                obs_map = {
                    "area": "area_name",
                    "location": "area_name",
                    "findings": "inspection_findings",
                    "issue": "inspection_findings",
                    "thermal": "thermal_findings",
                    "readings": "thermal_findings",
                    "images": "relevant_images"
                }
                for old, new in obs_map.items():
                    if old in obs and new not in obs:
                        obs[new] = obs.pop(old)
                normalized_obs.append(obs)
            else:
                normalized_obs.append({"area_name": str(obs)})
        data["area_wise_observations"] = normalized_obs

    # Normalize severity assessment
    if "severity_assessment" in data:
        sev = data["severity_assessment"]
        if isinstance(sev, str):
            data["severity_assessment"] = {"level": sev, "reasoning": "Not Available"}
            
    # Normalize recommended_actions (ensure it's a list)
    if "recommended_actions" in data and isinstance(data["recommended_actions"], str):
        data["recommended_actions"] = [data["recommended_actions"]]

    # Normalize missing_or_unclear_information (ensure it's a string)
    if "missing_or_unclear_information" in data and isinstance(data["missing_or_unclear_information"], list):
        data["missing_or_unclear_information"] = ", ".join([str(i) for i in data["missing_or_unclear_information"]])

    return data


# ── Generate flow ──
if generate_btn:
    if not api_key:
        st.error(f"Enter your {provider} API Key or set it in .env file."); st.stop()
    if not inspection_file or not thermal_file:
        st.error("Upload both PDFs."); st.stop()

    with st.status("Extracting data from PDFs...", expanded=True) as status:
        insp_text, insp_images = extract_from_pdf(inspection_file.read(), "Inspection")
        therm_text, therm_images = extract_from_pdf(thermal_file.read(), "Thermal")
        all_images = insp_images + therm_images
        combined_text = insp_text + "\n" + therm_text
        image_list_str = "\n".join(
            f"- {img['filename']}  (Source: {img['source']}, Page {img['page']})  Context: \"{img['page_context'][:120]}...\""
            for img in all_images
        )
        st.write(f"Extracted {len(insp_images)} inspection + {len(therm_images)} thermal images")
        status.update(label=f"Extraction done - {len(all_images)} images", state="complete")

    with st.status("AI analyzing and structuring report...", expanded=True) as status:
        try:
            raw_data = generate_ddr(provider, api_key, combined_text, image_list_str)
            report_data = normalize_report_data(raw_data)
            status.update(label="DDR structured successfully", state="complete")
        except Exception as e:
            status.update(label="Error", state="error")
            st.error(f"{provider} API error: {e}"); st.stop()

    with st.status("Building PDF...", expanded=True) as status:
        try:
            # Ensure report_data perfectly matches our schema (fills in missing fields)
            validated_report = DDRReport.model_validate(report_data).model_dump()
            pdf_path = os.path.join(OUTPUT_DIR, "DDR_Report.pdf")
            build_ddr_pdf(validated_report, all_images, IMAGES_DIR, pdf_path)
            status.update(label="PDF ready!", state="complete")
        except Exception as e:
            status.update(label="PDF Build Error", state="error")
            st.error(f"Error structuring data for PDF: {e}")
            # Fallback: try building with raw data if validation fails
            pdf_path = os.path.join(OUTPUT_DIR, "DDR_Report.pdf")
            build_ddr_pdf(report_data, all_images, IMAGES_DIR, pdf_path)

    # Save validated report for UI preview
    st.session_state["report_data"] = validated_report if 'validated_report' in locals() else report_data
    st.session_state["all_images"] = all_images
    st.session_state["pdf_path"] = pdf_path


# ─────────────────────────────────────────────
# Render report + download
# ─────────────────────────────────────────────

def get_img_path(filename, images):
    for img in images:
        if img["filename"] == filename and os.path.exists(img["filepath"]):
            return img["filepath"]
    p = os.path.join(IMAGES_DIR, filename)
    return p if os.path.exists(p) else None


if "report_data" in st.session_state:
    report = st.session_state["report_data"]
    images = st.session_state["all_images"]
    pdf_path = st.session_state.get("pdf_path")

    # ── Download button ──
    if pdf_path and os.path.exists(pdf_path):
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with open(pdf_path, "rb") as f:
                st.download_button(
                    "Download DDR Report (PDF)",
                    data=f, file_name="DDR_Report.pdf",
                    mime="application/pdf", use_container_width=True, type="primary",
                )

    st.markdown("---")
    st.header("DDR Report Preview")

    # 1
    st.subheader("1. Property Issue Summary")
    st.info(report.get("property_issue_summary", "Not Available"))

    # 2
    st.subheader("2. Area-wise Observations")
    for idx, obs in enumerate(report.get("area_wise_observations", [])):
        # Defensive check
        if isinstance(obs, str):
            obs = {"area_name": obs, "inspection_findings": "Not Available", "thermal_findings": "Not Available", "relevant_images": []}
            
        with st.expander(f"{obs.get('area_name', 'Unknown')}", expanded=True):
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown("**Inspection Findings:**")
                st.write(obs.get("inspection_findings", "Not Available"))
                st.markdown("**Thermal Findings:**")
                st.write(obs.get("thermal_findings", "Not Available"))
            with c2:
                st.markdown("**Images:**")
                shown = 0
                for ref in obs.get("relevant_images", []):
                    iid = ref.get("image_id", "")
                    if iid and iid.lower() != "image not available":
                        p = get_img_path(iid, images)
                        if p:
                            st.image(p, caption=ref.get("caption", ""), use_container_width=True)
                            shown += 1
                if shown == 0:
                    st.caption("Image Not Available")

    # 3
    st.subheader("3. Probable Root Cause")
    st.write(report.get("probable_root_cause", "Not Available"))

    # 4
    st.subheader("4. Severity Assessment")
    sev = report.get("severity_assessment", {})
    if isinstance(sev, str):
        sev = {"level": sev, "reasoning": "Not Available"}
    elif not isinstance(sev, dict):
        sev = {"level": "Not Available", "reasoning": "Not Available"}
        
    lvl = sev.get("level", "N/A")
    severity_colors = {"critical": "red", "high": "orange", "medium": "goldenrod", "low": "green"}
    sev_color = severity_colors.get(lvl.lower(), "gray")
    st.markdown(f'### <span style="color:{sev_color};">&#9679;</span> {lvl}', unsafe_allow_html=True)
    st.write(sev.get("reasoning", "Not Available"))

    # 5
    st.subheader("5. Recommended Actions")
    for i, a in enumerate(report.get("recommended_actions", []), 1):
        st.markdown(f"**{i}.** {a}")

    # 6
    st.subheader("6. Additional Notes")
    st.write(report.get("additional_notes", "Not Available"))

    # 7
    st.subheader("7. Missing or Unclear Information")
    m = report.get("missing_or_unclear_information", "Not Available")
    st.warning(m) if m.lower() != "not available" else st.success("All information is consistent.")
