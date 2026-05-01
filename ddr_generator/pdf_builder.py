"""
Generates a professional DDR PDF matching the Main DDR.pdf format.
Uses fpdf2 with Unicode font support.
"""
import os
from fpdf import FPDF
from PIL import Image


class DDRPdf(FPDF):
    BLUE = (30, 60, 120)
    DARK = (40, 40, 40)
    GRAY = (100, 100, 100)
    LIGHT_GRAY = (220, 220, 220)
    WHITE = (255, 255, 255)

    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=25)
        # Use built-in core fonts only (ASCII safe)

    def header(self):
        if self.page_no() <= 2:
            return
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*self.GRAY)
        self.cell(0, 5, "Detailed Diagnosis Report", align="L")
        self.cell(0, 5, "AI DDR Generator", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*self.LIGHT_GRAY)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*self.GRAY)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    # --- helpers ---
    def section_heading(self, text):
        if self.get_y() > 250:
            self.add_page()
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*self.BLUE)
        self.set_fill_color(235, 240, 250)
        safe_text = self._safe(text)
        self.cell(0, 10, f"  {safe_text}", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def sub_heading(self, text):
        if self.get_y() > 260:
            self.add_page()
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(50, 50, 50)
        self.cell(0, 8, self._safe(text), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*self.BLUE)
        self.line(10, self.get_y(), 80, self.get_y())
        self.ln(3)

    def _safe(self, text):
        """Strip non-latin1 chars and handle lists."""
        if not text:
            return ""
        if isinstance(text, list):
            text = ", ".join([str(i) for i in text])
        if not isinstance(text, str):
            text = str(text)
        return text.encode("latin-1", errors="replace").decode("latin-1")

    def para(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*self.DARK)
        self.multi_cell(0, 5.5, self._safe(text))
        self.ln(2)

    def bold_para(self, label, text):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*self.DARK)
        self.write(5.5, self._safe(label) + " ")
        self.set_font("Helvetica", "", 10)
        self.write(5.5, self._safe(text))
        self.ln(7)

    def bullet_item(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*self.DARK)
        x = self.get_x()
        self.cell(5, 5.5, "-")
        self.multi_cell(180, 5.5, self._safe(text))
        self.ln(1)

    def add_img(self, path, w=85, caption=""):
        if not path or not os.path.exists(path):
            self.set_font("Helvetica", "I", 9)
            self.set_text_color(180, 50, 50)
            self.cell(0, 6, "[Image Not Available]", new_x="LMARGIN", new_y="NEXT")
            self.ln(2)
            return
        try:
            img = Image.open(path)
            aspect = img.height / img.width
            h = w * aspect
            # cap max height
            if h > 120:
                h = 120
                w = h / aspect
            if self.get_y() + h + 10 > 270:
                self.add_page()
            # center image
            x_pos = (210 - w) / 2
            self.image(path, x=x_pos, w=w, h=h)
            self.ln(h + 2)
            if caption:
                self.set_font("Helvetica", "I", 8)
                self.set_text_color(*self.GRAY)
                self.cell(0, 5, self._safe(caption), align="C", new_x="LMARGIN", new_y="NEXT")
                self.ln(3)
        except Exception:
            self.set_font("Helvetica", "I", 9)
            self.set_text_color(180, 50, 50)
            self.cell(0, 6, "[Image could not be loaded]", new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

    def add_two_images(self, path1, cap1, path2, cap2):
        """Place two images side by side like the reference DDR."""
        w = 85
        y_start = self.get_y()
        # check space
        max_h = 80
        if y_start + max_h + 10 > 270:
            self.add_page()
            y_start = self.get_y()

        for i, (path, cap) in enumerate([(path1, cap1), (path2, cap2)]):
            x_pos = 12 + i * 97
            if path and os.path.exists(path):
                try:
                    img = Image.open(path)
                    aspect = img.height / img.width
                    h = min(w * aspect, max_h)
                    actual_w = h / aspect if h == max_h else w
                    self.image(path, x=x_pos, y=y_start, w=actual_w, h=h)
                    self.set_xy(x_pos, y_start + h + 1)
                    if cap:
                        self.set_font("Helvetica", "I", 7)
                        self.set_text_color(*self.GRAY)
                        self.cell(actual_w, 4, self._safe(cap[:60]), align="C")
                except Exception:
                    pass
        self.set_y(y_start + max_h + 8)


def build_ddr_pdf(report: dict, images: list, images_dir: str, output_path: str) -> str:
    pdf = DDRPdf()

    def find_img(filename):
        for img in images:
            if img["filename"] == filename and os.path.exists(img["filepath"]):
                return img["filepath"]
        p = os.path.join(images_dir, filename)
        return p if os.path.exists(p) else None

    # === COVER PAGE ===
    pdf.add_page()
    pdf.ln(30)
    pdf.set_fill_color(*DDRPdf.BLUE)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_text_color(*DDRPdf.WHITE)
    pdf.set_font("Helvetica", "B", 32)
    pdf.ln(60)
    pdf.cell(0, 15, "Detailed Diagnosis Report", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 16)
    pdf.ln(5)
    pdf.cell(0, 10, "(DDR)", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(30)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, "Generated by AI DDR Report Generator", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(60)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(200, 200, 220)
    pdf.cell(0, 6, "Auto-generated from Inspection and Thermal Report data", align="C", new_x="LMARGIN", new_y="NEXT")

    # === DISCLAIMER PAGE ===
    pdf.add_page()
    pdf.section_heading("Data and Information Disclaimer")
    pdf.para(
        "This property inspection is not an exhaustive inspection of the structure, systems, or components. "
        "The inspection may not reveal all deficiencies. A health checkup helps to reduce some of the risk "
        "involved in the property/structure and premises, but it cannot eliminate these risks, nor can the "
        "inspection anticipate future events or changes in performance due to changes in use or occupancy."
    )
    pdf.para(
        "An inspection addresses only those components and conditions that are present, visible, and "
        "accessible at the time of the inspection. The inspection report may address issues that are code-based; "
        "however, this is NOT a code compliance inspection and does NOT verify compliance with "
        "manufacturer's installation instructions. The inspection does NOT imply insurability or "
        "warrantability of the structure or its components."
    )
    pdf.para(
        "The inspection of this property is subject to limitations and conditions set out in this Report."
    )

    # === TABLE OF CONTENTS ===
    pdf.add_page()
    pdf.section_heading("Table of Contents")
    toc = [
        ("Section 1", "Property Issue Summary"),
        ("Section 2", "Area-wise Observations"),
        ("Section 3", "Probable Root Cause"),
        ("Section 4", "Severity Assessment"),
        ("Section 5", "Recommended Actions"),
        ("Section 6", "Additional Notes"),
        ("Section 7", "Missing or Unclear Information"),
        ("Section 8", "Limitation and Precaution Note"),
    ]
    for num, title in toc:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*DDRPdf.BLUE)
        pdf.cell(30, 8, num)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*DDRPdf.DARK)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # === SECTION 1: PROPERTY ISSUE SUMMARY ===
    pdf.add_page()
    pdf.section_heading("SECTION 1  PROPERTY ISSUE SUMMARY")
    pdf.para(report.get("property_issue_summary", "Not Available"))

    # === SECTION 2: AREA-WISE OBSERVATIONS ===
    pdf.add_page()
    pdf.section_heading("SECTION 2  AREA-WISE OBSERVATIONS")

    for idx, obs in enumerate(report.get("area_wise_observations", []), 1):
        # Defensive check: if the AI returned a list of strings instead of objects
        if isinstance(obs, str):
            obs = {"area_name": obs, "inspection_findings": "Not Available", "thermal_findings": "Not Available", "relevant_images": []}
            
        pdf.sub_heading(f"{idx}. {obs.get('area_name', 'Unknown Area')}")

        # Inspection findings
        pdf.bold_para("Inspection Findings:", obs.get("inspection_findings", "Not Available"))

        # Thermal findings
        pdf.bold_para("Thermal Findings:", obs.get("thermal_findings", "Not Available"))

        # Images - try to place two side by side like the reference DDR
        rel_imgs = obs.get("relevant_images", [])
        valid_imgs = []
        for ref in rel_imgs:
            iid = ref.get("image_id", "")
            if iid and iid.lower() != "image not available":
                p = find_img(iid)
                if p:
                    valid_imgs.append((p, ref.get("caption", "")))

        if len(valid_imgs) >= 2:
            # pairs side by side
            i = 0
            while i < len(valid_imgs):
                if i + 1 < len(valid_imgs):
                    pdf.add_two_images(
                        valid_imgs[i][0], valid_imgs[i][1],
                        valid_imgs[i+1][0], valid_imgs[i+1][1]
                    )
                    i += 2
                else:
                    pdf.add_img(valid_imgs[i][0], w=85, caption=valid_imgs[i][1])
                    i += 1
        elif len(valid_imgs) == 1:
            pdf.add_img(valid_imgs[0][0], w=90, caption=valid_imgs[0][1])
        else:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(180, 50, 50)
            pdf.cell(0, 6, "[Image Not Available]", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

        # separator
        pdf.set_draw_color(*DDRPdf.LIGHT_GRAY)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

    # === SECTION 3: PROBABLE ROOT CAUSE ===
    pdf.add_page()
    pdf.section_heading("SECTION 3  PROBABLE ROOT CAUSE")
    pdf.para(report.get("probable_root_cause", "Not Available"))

    # === SECTION 4: SEVERITY ASSESSMENT ===
    pdf.section_heading("SECTION 4  SEVERITY ASSESSMENT")
    sev = report.get("severity_assessment", {})
    if isinstance(sev, str):
        sev = {"level": sev, "reasoning": "Not Available"}
    elif not isinstance(sev, dict):
        sev = {"level": "Not Available", "reasoning": "Not Available"}
        
    level = sev.get("level", "Not Available")
    colors = {"critical": (200, 30, 30), "high": (220, 120, 20), "medium": (180, 160, 30), "low": (30, 150, 60)}
    c = colors.get(level.lower(), (80, 80, 80))

    # Severity badge
    pdf.set_fill_color(*c)
    pdf.set_text_color(*DDRPdf.WHITE)
    pdf.set_font("Helvetica", "B", 12)
    badge_text = f"  Severity: {level}  "
    badge_w = pdf.get_string_width(badge_text) + 10
    pdf.cell(badge_w, 10, badge_text, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.para(f"Reasoning: {sev.get('reasoning', 'Not Available')}")

    # === SECTION 5: RECOMMENDED ACTIONS ===
    pdf.add_page()
    pdf.section_heading("SECTION 5  RECOMMENDED ACTIONS")
    for i, action in enumerate(report.get("recommended_actions", []), 1):
        pdf.bold_para(f"{i}.", action)

    # === SECTION 6: ADDITIONAL NOTES ===
    pdf.ln(3)
    pdf.section_heading("SECTION 6  ADDITIONAL NOTES")
    pdf.para(report.get("additional_notes", "Not Available"))

    # === SECTION 7: MISSING OR UNCLEAR INFO ===
    pdf.section_heading("SECTION 7  MISSING OR UNCLEAR INFORMATION")
    pdf.para(report.get("missing_or_unclear_information", "Not Available"))

    # === SECTION 8: LIMITATION & PRECAUTION NOTE ===
    pdf.add_page()
    pdf.section_heading("SECTION 8  LIMITATION AND PRECAUTION NOTE")
    pdf.para(
        "Information provided in this report is a general overview of the most obvious repairs that may be "
        "needed. It is not intended to be an exhaustive list. The ultimate decision of what to repair or replace "
        "is the client's."
    )
    pdf.para(
        "Some conditions noted, such as structural cracks and other signs of settlement indicate a potential "
        "problem that the structure of the building, or at least part of it, is overstressed. A structure when "
        "stretched beyond its capacity, may collapse without further warning signs. When such cracks suddenly "
        "develop, or appear to widen and/or spread, the findings must be reported immediately to a "
        "Structural Engineer."
    )
    pdf.para(
        "THIS IS NOT A CODE COMPLIANCE INSPECTION. The system does not determine whether "
        "any aspect of the property complies with any past, present or future codes, regulations, "
        "laws, by-laws, ordinances or other regulatory requirements."
    )

    # Legal disclaimer
    pdf.ln(5)
    pdf.sub_heading("Legal Disclaimer")
    pdf.para(
        "This report provides observations based on data extracted from the provided inspection and "
        "thermal documents using AI analysis. Any recommendations should be verified by a qualified "
        "professional before undertaking repair or remediation work. This report is subject to the "
        "limitations and conditions described herein."
    )

    pdf.output(output_path)
    return output_path
