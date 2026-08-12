from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "soutenance" / "rapport_visuel_kpi_powerbi_iris.docx"

SCREENSHOTS = {
    "Vue d'ensemble": Path(r"C:\Users\wiem\Pictures\Screenshots\Capture d'écran 2026-07-26 200144.png"),
    "Priorisation & explication": Path(r"C:\Users\wiem\Pictures\Screenshots\Capture d'écran 2026-07-26 200155.png"),
    "Clients & recurrence": Path(r"C:\Users\wiem\Pictures\Screenshots\Capture d'écran 2026-07-26 200200.png"),
    "Etat technique des vehicules": Path(r"C:\Users\wiem\Pictures\Screenshots\Capture d'écran 2026-07-26 200207.png"),
    "Qualite & gouvernance": Path(r"C:\Users\wiem\Pictures\Screenshots\Capture d'écran 2026-07-26 200220.png"),
}


ACCENT = "2F9AA0"
BLUE = "1F4D78"
LIGHT = "EAF4F5"
SOFT = "F4F6F9"
GOLD = "F5C04A"
RED = "B3392F"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_text(cell, text: str, bold: bool = False, color: str | None = None) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(8.5)
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def style_table(table, header_fill: str = LIGHT) -> None:
    table.autofit = False
    for i, row in enumerate(table.rows):
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_borders = tc_pr.first_child_found_in("w:tcBorders")
            if tc_borders is None:
                tc_borders = OxmlElement("w:tcBorders")
                tc_pr.append(tc_borders)
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                tag = f"w:{edge}"
                element = tc_borders.find(qn(tag))
                if element is None:
                    element = OxmlElement(tag)
                    tc_borders.append(element)
                element.set(qn("w:val"), "single")
                element.set(qn("w:sz"), "4")
                element.set(qn("w:color"), "D9E2E3")
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(8.5)
        if i == 0:
            for cell in row.cells:
                set_cell_shading(cell, header_fill)
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.bold = True
                        run.font.color.rgb = RGBColor.from_string("0B2545")


def add_title(doc: Document) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Rapport Visuel Power BI IRIS")
    r.bold = True
    r.font.size = Pt(24)
    r.font.color.rgb = RGBColor.from_string(BLUE)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("KPI, mesures DAX, storytelling et defense des seuils")
    r.font.size = Pt(12)
    r.font.color.rgb = RGBColor.from_string("556B73")

    add_callout(
        doc,
        "Message directeur",
        "Power BI est la couche de pilotage d'IRIS: il transforme les scores en lecture portefeuille. "
        "Chaque page repond a une question manager: volume, priorisation, recurrence, etat technique, qualite et gouvernance.",
        fill=LIGHT,
    )


def add_callout(doc: Document, title: str, text: str, fill: str = SOFT) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    table.columns[0].width = Inches(9.4)
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(title)
    r.bold = True
    r.font.size = Pt(10)
    r.font.color.rgb = RGBColor.from_string(BLUE)
    p2 = cell.add_paragraph()
    r2 = p2.add_run(text)
    r2.font.size = Pt(9.5)
    r2.font.color.rgb = RGBColor.from_string("2B2B2B")
    doc.add_paragraph()


def add_kpi_table(doc: Document, rows: list[tuple[str, str, str]]) -> None:
    table = doc.add_table(rows=1, cols=3)
    hdr = table.rows[0].cells
    for cell, text in zip(hdr, ["KPI", "Lecture metier", "DAX / Calcul"]):
        set_cell_text(cell, text, bold=True)
    widths = [1.85, 3.35, 4.2]
    for row in table.rows:
        for idx, width in enumerate(widths):
            row.cells[idx].width = Inches(width)
    for kpi, meaning, dax in rows:
        cells = table.add_row().cells
        set_cell_text(cells[0], kpi, bold=True, color=BLUE)
        set_cell_text(cells[1], meaning)
        set_cell_text(cells[2], dax)
    style_table(table)
    doc.add_paragraph()


def add_dax_block(doc: Document, title: str, code: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(title)
    r.bold = True
    r.font.color.rgb = RGBColor.from_string(BLUE)
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    set_cell_shading(cell, "F7F7F7")
    p = cell.paragraphs[0]
    for line_no, line in enumerate(code.strip().splitlines()):
        if line_no:
            p.add_run("\n")
        run = p.add_run(line)
        run.font.name = "Consolas"
        run.font.size = Pt(8)
    doc.add_paragraph()


def add_screenshot(doc: Document, path: Path) -> None:
    if path.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run()
        run.add_picture(str(path), width=Inches(9.2))


def add_page_section(
    doc: Document,
    title: str,
    story: str,
    threshold: str,
    kpis: list[tuple[str, str, str]],
    dax_blocks: list[tuple[str, str]] | None = None,
    screenshot: Path | None = None,
) -> None:
    doc.add_page_break()
    doc.add_heading(title, level=1)
    if screenshot:
        add_screenshot(doc, screenshot)
    add_callout(doc, "Storytelling", story, fill=LIGHT)
    add_callout(doc, "Defense des seuils", threshold, fill="FFF3CC")
    doc.add_heading("KPI et mesures", level=2)
    add_kpi_table(doc, kpis)
    for block_title, code in dax_blocks or []:
        add_dax_block(doc, block_title, code)


def main() -> None:
    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = Inches(11)
    section.page_height = Inches(8.5)
    section.top_margin = Inches(0.45)
    section.bottom_margin = Inches(0.45)
    section.left_margin = Inches(0.55)
    section.right_margin = Inches(0.55)

    styles = doc.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(9.5)
    styles["Heading 1"].font.color.rgb = RGBColor.from_string(BLUE)
    styles["Heading 1"].font.size = Pt(16)
    styles["Heading 2"].font.color.rgb = RGBColor.from_string(BLUE)
    styles["Heading 2"].font.size = Pt(12)

    add_title(doc)

    doc.add_heading("Architecture des mesures", level=1)
    add_callout(
        doc,
        "Principe de lecture",
        "Les KPI sont construits sur les vues Power BI en lecture seule. Les mesures principales sont centralisees dans la table _Mesures. "
        "Les filtres periode, niveau d'attention, gouvernorat, confiance et raison principale pilotent les visuels sans modifier les donnees source.",
        fill=LIGHT,
    )
    add_kpi_table(
        doc,
        [
            ("Grain dossier", "Une ligne par dossier racine pour piloter le portefeuille.", "DISTINCTCOUNT('v_dossier_attention'[claim_root_id])"),
            ("Grain garantie", "Une ligne sinistre-garantie pour expliquer les details.", "COUNTROWS('v_claim_attention_guarantee')"),
            ("Grain signal", "Une ligne par signal explicatif emis.", "COUNTROWS('v_signal_detail')"),
            ("Mois complet", "Exclut le dernier mois partiel pour fiabiliser les tendances.", "Mois Complet Donnees = 1"),
        ],
    )

    add_dax_block(
        doc,
        "Filtre mois complet utilise sur la page Vue d'ensemble",
        """
Mois Complet Donnees =
VAR DernierMoisPresent =
    CALCULATE(
        MAX('v_dossier_attention'[claim_month]),
        ALL('v_dossier_attention')
    )
RETURN
    IF('v_dossier_attention'[claim_month] < DernierMoisPresent, 1, 0)
""",
    )

    add_page_section(
        doc,
        "Page 1 - Vue d'ensemble du portefeuille",
        "Cette page donne la photo globale: volume score, part haute attention, dossiers prioritaires, exposition financiere et confiance. "
        "Elle sert a montrer que le moteur reste selectif et que les donnees sont exploitables.",
        "Reference Pct Haute Attention = 5%. Ce seuil est un repere candidat de surveillance: assez bas pour eviter de saturer la revue humaine, "
        "mais ajustable apres validation de la capacite reelle de l'equipe fraude. Les KPI sont filtres sur les mois complets pour eviter un biais de mois partiel.",
        [
            ("Dossiers scores", "Nombre de dossiers analyses sur la periode.", "Dossiers Scores = DISTINCTCOUNT('v_dossier_attention'[claim_root_id])"),
            ("Taux haute attention", "Part des dossiers renforces ou prioritaires.", "Pct Haute Attention = DIVIDE([Dossiers Haute Attention], [Dossiers Scores])"),
            ("Dossiers prioritaires", "Dossiers avec score >= 75.", "Dossiers Prioritaires = CALCULATE([Dossiers Scores], level = \"Examen prioritaire suggere\")"),
            ("Montant sous haute attention", "Exposition financiere des dossiers renforces + prioritaires.", "CALCULATE([Montant Sinistres], level IN {renforce, prioritaire})"),
            ("% confiance elevee", "Part des dossiers avec donnees fiables.", "Pct Confiance Haute = DIVIDE(CALCULATE([Dossiers Scores], confidence_level=\"HIGH\"), [Dossiers Scores])"),
        ],
        [
            (
                "Mesures principales",
                """
Dossiers Haute Attention =
CALCULATE([Dossiers Scores],
    'v_dossier_attention'[dossier_attention_level]
        IN {\"Examen renforce suggere\", \"Examen prioritaire suggere\"})

Reference Pct Haute Attention = 0.05
Target Confiance Haute = 0.80
""",
            ),
            (
                "Comparaison M-1",
                """
Dossiers Scores M-1 =
VAR MoisCourant = MAX('v_dossier_attention'[claim_month])
RETURN CALCULATE([Dossiers Scores],
    'v_dossier_attention'[claim_month] = EDATE(MoisCourant, -1))
""",
            ),
        ],
        SCREENSHOTS["Vue d'ensemble"],
    )

    add_page_section(
        doc,
        "Page 2 - Priorisation & explication",
        "Cette page explique pourquoi les dossiers montent en priorite. Elle combine charge de revue, exposition financiere, contribution des familles de signaux et liste des dossiers prioritaires.",
        "Le seuil prioritaire est score >= 75. Il correspond aux dossiers qui cumulent plusieurs signaux forts. Le ML est plafonne: il explique une atypicite, mais ne remplace pas les regles metier.",
        [
            ("Dossiers prioritaires", "Volume de dossiers en examen prioritaire.", "Dossiers Prioritaires"),
            ("Taux prioritaire", "Part des prioritaires dans le portefeuille.", "Pct Prioritaires = DIVIDE([Dossiers Prioritaires], [Dossiers Scores])"),
            ("Exposition prioritaire", "Montant total des dossiers prioritaires.", "CALCULATE([Montant Sinistres], level=\"Examen prioritaire suggere\")"),
            ("Montant moyen prioritaire", "Enjeu financier moyen par dossier prioritaire.", "DIVIDE([Exposition Prioritaire], [Dossiers Prioritaires])"),
            ("Points attribues", "Somme des points expliquant les signaux.", "Points Attribues = SUM('v_signal_detail'[points])"),
        ],
        [
            (
                "DAX priorisation",
                """
Dossiers Prioritaires =
CALCULATE([Dossiers Scores],
    'v_dossier_attention'[dossier_attention_level] = \"Examen prioritaire suggere\")

Pct Prioritaires = DIVIDE([Dossiers Prioritaires], [Dossiers Scores])

Points Attribues = SUM('v_signal_detail'[points])
""",
            )
        ],
        SCREENSHOTS["Priorisation & explication"],
    )

    add_page_section(
        doc,
        "Page 3 - Clients & recurrence",
        "Cette page analyse la recurrence client: clients multi-sinistres, concentration de l'exposition et clients a reexaminer. Elle sert a detecter les poches de portefeuille qui demandent une revue plus structuree.",
        "Le seuil multi-sinistres 12 mois isole une recurrence recente. La lecture Pareto Top 20% montre si une minorite de clients concentre une part importante de l'exposition.",
        [
            ("Clients identifies", "Nombre de clients exploitables.", "Clients Identifies = COUNTROWS('v_client_cohort')"),
            ("Clients multi-sinistres 12M", "Clients ayant plusieurs dossiers recents.", "CALCULATE(COUNTROWS('v_client_cohort'), is_multiclaim_12m=TRUE())"),
            ("Taux clients multi-sinistres", "Part des clients recurrents.", "DIVIDE([Clients Multisinistres 12M], [Clients Identifies])"),
            ("Exposition clients recurrents", "Montant cumule porte par les clients recurrents.", "Montant Cumule Clients = SUM('v_client_cohort'[total_claim_amount])"),
            ("Concentration Top 20%", "Part de l'exposition portee par les 20% clients les plus exposes.", "Pareto: cumul montant par decile client"),
            ("Clients a reexaminer", "Clients avec recurrence et haute attention significatives.", "Filtre: dossiers haute attention + volume client"),
        ],
        [
            (
                "DAX clients",
                """
Clients Identifies = COUNTROWS('v_client_cohort')

Clients Multisinistres 12M =
CALCULATE(COUNTROWS('v_client_cohort'),
    'v_client_cohort'[is_multiclaim_12m] = TRUE())

Taux Clients Multi =
DIVIDE([Clients Multisinistres 12M], [Clients Identifies])

Montant Cumule Clients = SUM('v_client_cohort'[total_claim_amount])
""",
            )
        ],
        SCREENSHOTS["Clients & recurrence"],
    )

    add_page_section(
        doc,
        "Page 4 - Etat technique des vehicules",
        "Cette page valorise le module VHS et les inspections STAFIM. Elle montre l'etat technique observe, les vehicules sensibles, les defauts par point de controle et les signaux post-inspection.",
        "La fenetre 0-90 jours entre inspection et sinistre sert a garder un lien temporel defendable. Le VHS n'est pas une preuve de fraude: c'est un contexte technique pour orienter la verification.",
        [
            ("Vehicules scores VHS", "Nombre de vehicules avec score technique.", "Inspections VHS = COUNTROWS('v_vhs_score')"),
            ("Score VHS moyen", "Moyenne du score technique vehicule.", "Score VHS Moyen = AVERAGE('v_vhs_score'[vhs_final_score])"),
            ("Vehicules en etat sensible", "Vehicules critiques, immobilises ou a surveiller.", "COUNTROWS avec decision VHS sensible"),
            ("Delai moyen inspection -> sinistre", "Proximite temporelle entre inspection et sinistre.", "AVERAGE('v_post_inspection_signal'[days_inspection_to_claim])"),
            ("Signaux post-inspection", "Nombre de signaux inspection-sinistre valides.", "Signaux Post Inspection = COUNTROWS('v_post_inspection_signal')"),
            ("Defauts observes", "Volume de defauts par point de controle.", "Defauts Observes = SUM('v_inspection_checkpoint_defect'[defect_count])"),
        ],
        [
            (
                "DAX vehicules",
                """
Inspections VHS = COUNTROWS('v_vhs_score')

Score VHS Moyen = AVERAGE('v_vhs_score'[vhs_final_score])

Signaux Post Inspection = COUNTROWS('v_post_inspection_signal')

Delai Moyen Inspection Sinistre =
AVERAGE('v_post_inspection_signal'[days_inspection_to_claim])
""",
            )
        ],
        SCREENSHOTS["Etat technique des vehicules"],
    )

    add_page_section(
        doc,
        "Page 5 - Qualite & gouvernance",
        "Cette page prouve que le scoring est controle: niveau de confiance, donnees manquantes, dates invalides, migration historique, versions servies et derniers runs.",
        "La cible de confiance elevee est 80%. Les indicateurs qualite ne doivent pas augmenter le score d'attention: ils reduisent la confiance ou declenchent une verification de donnees.",
        [
            ("Confiance elevee", "Part des dossiers avec niveau HIGH.", "Pct Confiance Haute"),
            ("Clients non identifies", "Taux de dossiers sans client resolu.", "Pct Client Inconnu = MAX('v_quality_kpis'[pct_unknown_client])"),
            ("Dates invalides", "Taux de dates non exploitables.", "Pct Dates Invalides = MAX('v_quality_kpis'[pct_invalid_dates])"),
            ("Vehicules manquants", "Taux de dossiers sans vehicule relie.", "MAX('v_quality_kpis'[pct_missing_vehicle]) si expose"),
            ("Immatriculations VHS manquantes", "Taux de vehicules VHS sans immatriculation.", "MAX('v_quality_kpis'[pct_missing_vhs_registration]) si expose"),
            ("Pct Migration 2019", "Part potentiellement impactee par la migration historique.", "Pct Migration 2019 = MAX('v_quality_kpis'[pct_migration_2019])"),
            ("Versions servies", "Version active et run par moteur.", "Table v_governance / v_current_run"),
        ],
        [
            (
                "DAX qualite",
                """
Pct Confiance Haute =
DIVIDE(
    CALCULATE([Dossiers Scores],
        'v_dossier_attention'[confidence_level] = \"HIGH\"),
    [Dossiers Scores])

Pct Client Inconnu = MAX('v_quality_kpis'[pct_unknown_client])
Pct Dates Invalides = MAX('v_quality_kpis'[pct_invalid_dates])
Pct Migration 2019 = MAX('v_quality_kpis'[pct_migration_2019])
Target Confiance Haute = 0.80
""",
            )
        ],
        SCREENSHOTS["Qualite & gouvernance"],
    )

    doc.add_page_break()
    doc.add_heading("Annexe - Colonnes calculees Power BI", level=1)
    add_kpi_table(
        doc,
        [
            ("score_bin", "Regroupe les scores par tranches de 5 points pour les histogrammes.", "INT('v_dossier_attention'[dossier_attention_score] / 5) * 5"),
            ("claim_month", "Ramene chaque date sinistre au premier jour du mois.", "DATE(YEAR([claim_date]), MONTH([claim_date]), 1)"),
            ("tranche_sinistres", "Classe les clients selon le nombre de dossiers.", "IF([dossier_count] >= 5, \"5+\", FORMAT([dossier_count], \"0\"))"),
            ("Mois Complet Donnees", "Exclut le dernier mois disponible s'il est partiel.", "IF([claim_month] < DernierMoisPresent, 1, 0)"),
        ],
    )

    add_callout(
        doc,
        "Conclusion soutenance",
        "Les KPI Power BI ne sont pas seulement descriptifs: ils racontent la performance du dispositif IRIS. "
        "Ils montrent la selectivite du score, la charge de revue, les facteurs de priorisation, la recurrence client, le contexte technique vehicule et la fiabilite des donnees.",
        fill=LIGHT,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
