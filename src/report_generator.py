"""
Génération du rapport PDF professionnel d'inspection de pièce imprimée 3D.

Contenu du rapport :
    Page 1 — En-tête avec logo WE MAKE + informations de la session
    Section 1 — Résultats de calibration caméra (RMS, matrice, distorsion)
    Section 2 — Résultats de mesure dimensionnelle (L, l, Aire vs STL)
    Section 3 — Analyse des écarts et diagnostic
    Section 4 — Solutions et recommandations techniques complètes
              (calibration, dimensions, température, paramètres impression 3D)
    Pied de page — Horodatage, numéro de page

Usage :
    from report_generator import ReportGenerator
    gen = ReportGenerator(logo_path="/chemin/logo-dark.png")
    path = gen.generate(
        measurement=dim_measurement,
        stl_comparison=stl_result,
        calibration_result=calib_result,
        working_distance_mm=300.0,
        output_path="/chemin/rapport.pdf",
    )
"""

import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image as RLImage, KeepTogether,
)
from reportlab.platypus import PageBreak


# ---------------------------------------------------------------------------
# Palette de couleurs (cohérente avec le thème de l'application)
# ---------------------------------------------------------------------------
C_DARK      = colors.HexColor("#1A1A1A")
C_BLUE      = colors.HexColor("#185FA5")
C_BLUE_LIGHT= colors.HexColor("#378ADD")
C_GREEN     = colors.HexColor("#1D9E75")
C_RED       = colors.HexColor("#993C1D")
C_ORANGE    = colors.HexColor("#D85A30")
C_GREY_BG   = colors.HexColor("#F4F4F2")
C_GREY_MID  = colors.HexColor("#C8C8C4")
C_GREY_DARK = colors.HexColor("#5A5A5A")
C_WHITE     = colors.white


# ---------------------------------------------------------------------------
# Recommandations techniques complètes par type de problème
# ---------------------------------------------------------------------------

RECOMMENDATIONS = {
    "calibration_excellent": {
        "title": "Calibration caméra — Excellente",
        "color": C_GREEN,
        "icon": "✓",
        "description": (
            "L'erreur de reprojection RMS est inférieure à 0.5 px, ce qui "
            "correspond à une calibration de haute précision. Les paramètres "
            "intrinsèques (focale, centre optique) et les coefficients de "
            "distorsion sont fiables."
        ),
        "actions": [
            "Aucune action requise sur la calibration.",
            "Conserver ce fichier de calibration (YAML) et ne pas recalibrer "
            "sauf si la caméra est physiquement déplacée ou rechoquée.",
            "Vérifier périodiquement (tous les 2–3 mois) en recapturant "
            "2–3 images du board et en comparant le RMS obtenu.",
        ],
    },
    "calibration_good": {
        "title": "Calibration caméra — Bonne",
        "color": C_GREEN,
        "icon": "✓",
        "description": (
            "L'erreur de reprojection RMS est entre 0.5 et 1.0 px. "
            "La calibration est acceptable pour une utilisation industrielle "
            "standard. Une légère imprécision peut subsister sur les bords "
            "de l'image (distorsion résiduelle)."
        ),
        "actions": [
            "Utiliser la calibration actuelle — précision suffisante "
            "pour des pièces > 5 mm.",
            "Pour améliorer : capturer 15–20 images supplémentaires avec "
            "le board ChArUco sous des angles plus variés (inclinaisons "
            "de 30° à 45° dans toutes les directions).",
            "Retirer du jeu de calibration les images dont l'erreur "
            "individuelle dépasse 1.5× l'erreur moyenne (barres rouges "
            "dans le graphique).",
        ],
    },
    "calibration_acceptable": {
        "title": "Calibration caméra — Acceptable",
        "color": C_ORANGE,
        "icon": "⚠",
        "description": (
            "L'erreur de reprojection RMS est entre 1.0 et 2.0 px. "
            "Cette précision est insuffisante pour des mesures dimensionnelles "
            "fines (< 1 mm d'erreur visée). Les mesures actuelles comportent "
            "une incertitude systématique due à la distorsion résiduelle."
        ),
        "actions": [
            "Recalibrer en suivant le protocole strict ci-dessous.",
            "Vérifier que le board ChArUco est imprimé sur papier MAT "
            "(pas brillant, pas sur écran) et parfaitement plan.",
            "Augmenter le nombre d'images à 20–25, avec angles variés "
            "et distances variées (30–70 cm de la caméra).",
            "S'assurer que l'éclairage est uniforme et sans reflets "
            "sur le board pendant la capture.",
            "Retirer toutes les images avec erreur individuelle > 1.5 px "
            "avant de relancer la calibration.",
        ],
    },
    "calibration_bad": {
        "title": "Calibration caméra — Insuffisante",
        "color": C_RED,
        "icon": "✗",
        "description": (
            "L'erreur de reprojection RMS dépasse 2.0 px. La calibration "
            "est inutilisable pour des mesures dimensionnelles fiables. "
            "Les mesures actuelles ne sont pas exploitables."
        ),
        "actions": [
            "Ne pas utiliser les mesures de cette session.",
            "Recalibrer entièrement depuis zéro (supprimer toutes les images).",
            "Vérifier l'objectif de la caméra : poussière, rayure, "
            "condensation ? Nettoyer si nécessaire.",
            "Vérifier que la résolution de capture est cohérente entre "
            "la calibration et l'inspection (ne pas changer la résolution).",
            "Utiliser exclusivement le board ChArUco imprimé sur papier mat.",
            "Après recalibration, valider avec un étalon physique "
            "(règle graduée) avant de reprendre les inspections.",
        ],
    },
    "dim_ok": {
        "title": "Dimensions — Conformes",
        "color": C_GREEN,
        "icon": "✓",
        "description": (
            "Les dimensions mesurées sont dans la tolérance acceptable "
            "(écart < 2% par rapport au modèle STL de référence). "
            "La pièce est conforme aux spécifications théoriques."
        ),
        "actions": [
            "Pièce validée — peut passer à l'étape suivante du processus.",
            "Conserver les paramètres d'impression actuels.",
        ],
    },
    "dim_warning": {
        "title": "Dimensions — Écart modéré",
        "color": C_ORANGE,
        "icon": "⚠",
        "description": (
            "Les dimensions mesurées présentent un écart de 2% à 5% par "
            "rapport au modèle STL. Cet écart peut être dû à un retrait "
            "du matériau (shrinkage), une mauvaise calibration de "
            "l'extrudeuse, ou une température incorrecte."
        ),
        "actions": [
            "Vérifier et ajuster le facteur de flux (flow rate) de l'extrudeuse "
            "(typiquement réduire de 2–3% si la pièce est trop grande, "
            "augmenter si trop petite).",
            "Contrôler la température du plateau : un plateau trop chaud "
            "réduit l'adhérence et augmente le warping, causant des "
            "déformations dimensionnelles.",
            "Vérifier la calibration des steps/mm du moteur de l'axe Z "
            "(commande M92 sur les imprimantes Marlin).",
            "Pour le PLA : tester une réduction de température de 5°C "
            "pour limiter le gonflement thermique.",
            "Pour le PETG/ABS : vérifier que le cooling est adapté "
            "(trop de refroidissement = fragilité et retrait).",
            "Relancer une impression de test avec un cube d'étalonnage "
            "20×20×20 mm et mesurer au pied à coulisse.",
        ],
    },
    "dim_critical": {
        "title": "Dimensions — Écart critique",
        "color": C_RED,
        "icon": "✗",
        "description": (
            "Les dimensions mesurées présentent un écart supérieur à 5% "
            "par rapport au modèle STL. La pièce est hors tolérance et "
            "doit être rejetée. Des ajustements importants sont nécessaires."
        ),
        "actions": [
            "Rejeter la pièce — non conforme.",
            "Vérifier en priorité la calibration de l'extrudeuse "
            "(E-steps : commande M92 E<valeur>). Une sous-extrusion "
            "ou sur-extrusion importante cause des écarts > 5%.",
            "Contrôler le diamètre réel du filament (mesurer avec "
            "un pied à coulisse sur 5 points différents du rouleau, "
            "valeur attendue 1.75 mm ± 0.05 mm).",
            "Vérifier l'absence de bouchage partiel de la buse "
            "(partial clog) — symptôme : flux irrégulier, "
            "sous-extrusion sur les grandes surfaces.",
            "Recalibrer le bed leveling (mise à niveau du plateau).",
            "Vérifier que le profil de tranchage (slicer) utilise "
            "bien les bonnes dimensions de la buse installée.",
            "Comparer les paramètres de vitesse : une vitesse "
            "d'impression trop élevée réduit la précision dimensionnelle.",
        ],
    },
}

PRINT_PARAMS_GUIDE = [
    ("Température buse (PLA)", "190–220°C",
     "Trop haute → gonflement, stringing. Trop basse → sous-extrusion, "
     "manque d'adhérence entre couches. Tester par paliers de 5°C."),
    ("Température buse (PETG)", "230–250°C",
     "Matériau sensible à l'humidité. Sécher le filament 4h à 65°C "
     "si des bulles apparaissent. Réduire vitesse de 20% vs PLA."),
    ("Température buse (ABS)", "230–250°C",
     "Nécessite enceinte fermée (>45°C) pour éviter le warping. "
     "Ventilation réduite ou nulle pendant l'impression."),
    ("Température plateau", "50–60°C (PLA), 70–85°C (PETG), 90–110°C (ABS)",
     "Un plateau trop froid cause le warping (décollement des coins). "
     "Un plateau trop chaud cause l'elephant foot (pied d'éléphant)."),
    ("Vitesse d'impression", "40–60 mm/s standard",
     "Réduire à 20–30 mm/s pour les pièces de précision. "
     "La vitesse influe directement sur la précision dimensionnelle "
     "et l'adhérence entre couches."),
    ("Hauteur de couche", "0.1–0.3 mm",
     "0.1 mm : précision maximale (surfaces lisses, détails fins). "
     "0.3 mm : rapidité (surfaces rugueuses). Pour l'inspection "
     "dimensionnelle, 0.15–0.2 mm est recommandé."),
    ("Flux / Flow rate", "95–105%",
     "Calibrer avec un cube de test 20×20 mm. Si trop grand → réduire. "
     "Si trop petit → augmenter. Ajuster par paliers de 2%."),
    ("Remplissage (Infill)", "20–40% standard",
     "Pour des pièces mécaniques : 40–80%. Ne pas dépasser 80% sauf "
     "besoin spécifique (augmente warping et consommation matière)."),
    ("Périmètres (Perimeters)", "2–4 périmètres",
     "Augmenter à 4–6 pour les pièces mécaniques. Les périmètres "
     "déterminent la résistance des parois et la précision dimensionnelle."),
    ("Rétraction", "1–6 mm selon type extrudeuse",
     "Direct drive : 1–2 mm. Bowden : 4–7 mm. "
     "Trop de rétraction → bouchage. Pas assez → stringing."),
]


# ---------------------------------------------------------------------------
# Classe principale
# ---------------------------------------------------------------------------

class ReportGenerator:
    """
    Génère un rapport PDF professionnel d'inspection de pièce imprimée 3D.
    Utilise ReportLab Platypus pour un rendu de qualité industrielle.
    """

    PAGE_W, PAGE_H = A4
    MARGIN = 14 * mm

    def __init__(self):
        self._content_w = self.PAGE_W - 2 * self.MARGIN
        self._styles = self._build_styles()

    # ------------------------------------------------------------------
    # Styles ReportLab
    # ------------------------------------------------------------------
    def _build_styles(self):
        base = getSampleStyleSheet()
        s = {}

        s["title"] = ParagraphStyle(
            "PFATitle",
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=C_DARK,
            spaceAfter=4 * mm,
            alignment=TA_LEFT,
        )
        s["subtitle"] = ParagraphStyle(
            "PFASubtitle",
            fontName="Helvetica",
            fontSize=11,
            textColor=C_GREY_DARK,
            spaceAfter=6 * mm,
            alignment=TA_LEFT,
        )
        s["section"] = ParagraphStyle(
            "PFASection",
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=C_WHITE,
            spaceBefore=4 * mm,
            spaceAfter=3 * mm,
            leftIndent=0,
            backColor=C_BLUE,
            borderPad=4,
        )
        s["subsection"] = ParagraphStyle(
            "PFASubsection",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=C_BLUE,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
        )
        s["body"] = ParagraphStyle(
            "PFABody",
            fontName="Helvetica",
            fontSize=9,
            textColor=C_DARK,
            spaceAfter=2 * mm,
            leading=14,
            alignment=TA_JUSTIFY,
        )
        s["body_bold"] = ParagraphStyle(
            "PFABodyBold",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=C_DARK,
            spaceAfter=1 * mm,
            leading=14,
        )
        s["bullet"] = ParagraphStyle(
            "PFABullet",
            fontName="Helvetica",
            fontSize=9,
            textColor=C_DARK,
            spaceAfter=1.5 * mm,
            leftIndent=10 * mm,
            bulletIndent=4 * mm,
            leading=13,
        )
        s["caption"] = ParagraphStyle(
            "PFACaption",
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=C_GREY_DARK,
            spaceAfter=2 * mm,
            alignment=TA_CENTER,
        )
        s["footer"] = ParagraphStyle(
            "PFAFooter",
            fontName="Helvetica",
            fontSize=7,
            textColor=C_GREY_DARK,
            alignment=TA_CENTER,
        )
        s["verdict_ok"] = ParagraphStyle(
            "PFAVerdictOK",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=C_GREEN,
            spaceAfter=3 * mm,
            alignment=TA_CENTER,
        )
        s["verdict_warn"] = ParagraphStyle(
            "PFAVerdictWarn",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=C_ORANGE,
            spaceAfter=3 * mm,
            alignment=TA_CENTER,
        )
        s["verdict_bad"] = ParagraphStyle(
            "PFAVerdictBad",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=C_RED,
            spaceAfter=3 * mm,
            alignment=TA_CENTER,
        )
        return s

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------
    def _hr(self, color=C_GREY_MID, thickness=0.5):
        return HRFlowable(
            width="100%", thickness=thickness, color=color,
            spaceAfter=3 * mm, spaceBefore=1 * mm,
        )

    def _section_title(self, text):
        """Titre de section : bande bleue pleine largeur, texte centré blanc."""
        style = ParagraphStyle(
            "SectionTitle",
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=C_WHITE,
            alignment=TA_CENTER,
            leading=18,
        )
        p = Paragraph(text, style)
        tbl = Table([[p]], colWidths=[self._content_w])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return tbl

    def _table(self, data, col_widths, style_extra=None):
        """Crée un tableau ReportLab avec wrap automatique dans toutes les cellules."""
        body_style = ParagraphStyle(
            "TblBody", fontName="Helvetica", fontSize=8.5,
            textColor=C_DARK, leading=12,
        )
        hdr_style = ParagraphStyle(
            "TblHdr", fontName="Helvetica-Bold", fontSize=8.5,
            textColor=C_WHITE, leading=12,
        )

        # Envelopper chaque cellule dans un Paragraph pour forcer le word-wrap
        wrapped = []
        for r_idx, row in enumerate(data):
            wrapped_row = []
            for cell in row:
                if isinstance(cell, str):
                    st = hdr_style if r_idx == 0 else body_style
                    wrapped_row.append(Paragraph(cell, st))
                else:
                    wrapped_row.append(cell)
            wrapped.append(wrapped_row)

        ts = [
            ("BACKGROUND",    (0, 0), (-1, 0),  C_BLUE),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_GREY_BG]),
            ("GRID",          (0, 0), (-1, -1), 0.4, C_GREY_MID),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        if style_extra:
            ts.extend(style_extra)
        t = Table(wrapped, colWidths=col_widths)
        t.setStyle(TableStyle(ts))
        return t

    # ------------------------------------------------------------------
    # En-tête de page (logo + titre)
    # ------------------------------------------------------------------
    def _build_header(self, session_info):
        story = []
        content_w = self._content_w

        # En-tête textuel centré (pas de logo)
        title_style = ParagraphStyle(
            "ReportTitle",
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=C_BLUE,
            alignment=TA_CENTER,
            spaceAfter=2 * mm,
        )
        sub_style = ParagraphStyle(
            "ReportSub",
            fontName="Helvetica",
            fontSize=10,
            textColor=C_GREY_DARK,
            alignment=TA_CENTER,
            spaceAfter=4 * mm,
        )
        story.append(Paragraph("Rapport d'inspection", title_style))
        story.append(Paragraph(
            "Pièce imprimée 3D — Analyse dimensionnelle et recommandations",
            sub_style,
        ))
        story.append(self._hr(C_BLUE, thickness=1.5))

        # Bandeau d'informations session
        info_data = [
            ["Date / Heure", session_info.get("datetime", "—"),
             "Pièce inspectée", session_info.get("piece_name", "—")],
            ["Opérateur", session_info.get("operator", "Station automatique"),
             "Modèle IA", session_info.get("model_name", "YOLOv8-seg")],
            ["Distance caméra–pièce",
             f"{session_info.get('working_distance_mm', '—')} mm"
             if isinstance(session_info.get('working_distance_mm'), (int, float))
             else session_info.get('working_distance_mm', '—'),
             "RMS calibration", session_info.get("rms_calib", "—")],
        ]
        col_w = content_w / 4
        info_table = Table(
            info_data,
            colWidths=[col_w * 0.85, col_w * 1.15, col_w * 0.85, col_w * 1.15],
        )
        info_table.setStyle(TableStyle([
            ("FONTNAME",  (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME",  (2, 0), (2, -1), "Helvetica-Bold"),
            ("FONTNAME",  (1, 0), (1, -1), "Helvetica"),
            ("FONTNAME",  (3, 0), (3, -1), "Helvetica"),
            ("FONTSIZE",  (0, 0), (-1, -1), 8.5),
            ("TEXTCOLOR", (0, 0), (0, -1), C_GREY_DARK),
            ("TEXTCOLOR", (2, 0), (2, -1), C_GREY_DARK),
            ("BACKGROUND",(0, 0), (-1, -1), C_GREY_BG),
            ("GRID",      (0, 0), (-1, -1), 0.4, C_GREY_MID),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_WHITE, C_GREY_BG]),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 5 * mm))
        return story

    # ------------------------------------------------------------------
    # Section 1 — Calibration caméra
    # ------------------------------------------------------------------
    def _build_calibration_section(self, calib_data):
        story = []
        story.append(self._section_title("1 — Calibration caméra (ChArUco)"))
        story.append(Spacer(1, 2 * mm))

        rms = calib_data.get("rms", None)
        fx  = calib_data.get("fx", None)
        fy  = calib_data.get("fy", None)
        cx  = calib_data.get("cx", None)
        cy  = calib_data.get("cy", None)
        dist = calib_data.get("dist_coeffs", [])
        n_img = calib_data.get("n_images", "—")

        # Tableau paramètres intrinsèques
        intrinsic_data = [
            ["Paramètre", "Valeur", "Description"],
            ["Erreur RMS (reprojection)",
             f"{rms:.4f} px" if rms is not None else "—",
             "Précision globale — objectif < 1.0 px"],
            ["Focale fx",
             f"{fx:.2f} px" if fx is not None else "—",
             "Longueur focale axe horizontal"],
            ["Focale fy",
             f"{fy:.2f} px" if fy is not None else "—",
             "Longueur focale axe vertical"],
            ["Centre optique cx",
             f"{cx:.2f} px" if cx is not None else "—",
             "Position du centre optique X"],
            ["Centre optique cy",
             f"{cy:.2f} px" if cy is not None else "—",
             "Position du centre optique Y"],
            ["Images utilisées", str(n_img),
             "Nombre d'images valides pour la calibration"],
        ]
        if dist:
            names = ["k1", "k2", "p1", "p2", "k3"]
            for i, v in enumerate(dist[:5]):
                intrinsic_data.append([
                    f"Distorsion {names[i]}",
                    f"{v:.6f}",
                    "Radiale" if i in [0, 1, 4] else "Tangentielle",
                ])

        content_w = self._content_w
        story.append(self._table(
            intrinsic_data,
            col_widths=[content_w * 0.35, content_w * 0.25, content_w * 0.40],
        ))
        story.append(Spacer(1, 3 * mm))

        # Diagnostic calibration
        if rms is not None:
            if rms < 0.5:
                key = "calibration_excellent"
            elif rms < 1.0:
                key = "calibration_good"
            elif rms < 2.0:
                key = "calibration_acceptable"
            else:
                key = "calibration_bad"
            story.extend(self._build_recommendation_block(key))

        return story

    # ------------------------------------------------------------------
    # Section 2 — Mesures dimensionnelles
    # ------------------------------------------------------------------
    def _build_measurement_section(self, measurement, stl_comparison):
        story = []
        story.append(self._section_title("2 — Mesures dimensionnelles"))
        story.append(Spacer(1, 2 * mm))

        content_w = self._content_w

        # Tableau mesures
        meas_data = [["Dimension", "Mesurée", "STL (théorique)", "Écart (mm)", "Écart (%)", "Statut"]]

        def status_cell(pct):
            if pct is None:
                return "—"
            if abs(pct) < 2:
                return "✓ Conforme"
            elif abs(pct) < 5:
                return "⚠ Modéré"
            else:
                return "✗ Critique"

        if measurement and stl_comparison:
            meas_data.append([
                "Longueur (L)",
                f"{stl_comparison.measured_length_mm:.2f} mm",
                f"{stl_comparison.theoretical_length_mm:.2f} mm",
                f"{stl_comparison.error_length_mm:+.2f} mm",
                f"{stl_comparison.error_length_pct:+.1f} %",
                status_cell(stl_comparison.error_length_pct),
            ])
            meas_data.append([
                "Largeur (l)",
                f"{stl_comparison.measured_width_mm:.2f} mm",
                f"{stl_comparison.theoretical_width_mm:.2f} mm",
                f"{stl_comparison.error_width_mm:+.2f} mm",
                f"{stl_comparison.error_width_pct:+.1f} %",
                status_cell(stl_comparison.error_width_pct),
            ])
        elif measurement:
            meas_data.append([
                "Longueur (L)", f"{measurement.length_mm:.2f} mm",
                "—", "—", "—", "Sans STL",
            ])
            meas_data.append([
                "Largeur (l)", f"{measurement.width_mm:.2f} mm",
                "—", "—", "—", "Sans STL",
            ])

        if measurement:
            meas_data.append([
                "Aire", f"{measurement.area_mm2:.1f} mm2",
                "—", "—", "—", "Info",
            ])

        col_w = [
            content_w * 0.18,
            content_w * 0.16,
            content_w * 0.18,
            content_w * 0.16,
            content_w * 0.14,
            content_w * 0.18,
        ]

        style_extra = []
        if stl_comparison:
            for row_i, pct in enumerate(
                [stl_comparison.error_length_pct, stl_comparison.error_width_pct], start=1
            ):
                if abs(pct) < 2:
                    c = C_GREEN
                elif abs(pct) < 5:
                    c = C_ORANGE
                else:
                    c = C_RED
                style_extra.append(("TEXTCOLOR", (5, row_i), (5, row_i), c))
                style_extra.append(("FONTNAME", (5, row_i), (5, row_i), "Helvetica-Bold"))

        story.append(self._table(meas_data, col_widths=col_w, style_extra=style_extra))
        story.append(Spacer(1, 3 * mm))

        # Verdict global
        if stl_comparison:
            max_pct = max(abs(stl_comparison.error_length_pct),
                          abs(stl_comparison.error_width_pct))
            if max_pct < 2:
                verdict_style = self._styles["verdict_ok"]
                verdict_text = "✓ PIÈCE CONFORME — Dimensions dans la tolérance"
                dim_key = "dim_ok"
            elif max_pct < 5:
                verdict_style = self._styles["verdict_warn"]
                verdict_text = "⚠ ÉCART MODÉRÉ — Ajustements recommandés"
                dim_key = "dim_warning"
            else:
                verdict_style = self._styles["verdict_bad"]
                verdict_text = "✗ PIÈCE NON CONFORME — Écart critique"
                dim_key = "dim_critical"

            story.append(KeepTogether([
                Paragraph(verdict_text, verdict_style),
                self._hr(C_GREY_MID),
            ]))
            story.extend(self._build_recommendation_block(dim_key))

        return story

    # ------------------------------------------------------------------
    # Section 3 — Paramètres d'impression 3D recommandés
    # ------------------------------------------------------------------
    def _build_print_params_section(self):
        story = []
        story.append(self._section_title("3 — Guide des paramètres d'impression 3D"))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            "Les paramètres ci-dessous constituent la référence pour optimiser "
            "la précision dimensionnelle des pièces imprimées. En cas d'écart "
            "constaté, ajuster en priorité les paramètres marqués ★.",
            self._styles["body"],
        ))
        story.append(Spacer(1, 2 * mm))

        content_w = self._content_w
        param_data = [["Paramètre", "Valeur recommandée", "Impact et conseils"]]
        for name, val, tip in PRINT_PARAMS_GUIDE:
            param_data.append([name, val, tip])

        story.append(self._table(
            param_data,
            col_widths=[content_w * 0.22, content_w * 0.22, content_w * 0.56],
        ))
        return story

    # ------------------------------------------------------------------
    # Bloc de recommandation générique
    # ------------------------------------------------------------------
    def _build_recommendation_block(self, key):
        rec = RECOMMENDATIONS.get(key, {})
        if not rec:
            return []

        story = []
        header = Paragraph(
            f"{rec['icon']}  {rec['title']}",
            ParagraphStyle(
                "RecHeader",
                fontName="Helvetica-Bold",
                fontSize=10,
                textColor=rec["color"],
                spaceBefore=2 * mm,
                spaceAfter=1 * mm,
            ),
        )
        desc = Paragraph(rec["description"], self._styles["body"])
        items = [
            Paragraph(f"• {a}", self._styles["bullet"])
            for a in rec.get("actions", [])
        ]
        story.append(KeepTogether([header, desc] + items))
        story.append(Spacer(1, 2 * mm))
        return story

    # ------------------------------------------------------------------
    # Pied de page
    # ------------------------------------------------------------------
    def _footer_func(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(C_GREY_DARK)

        footer_text = (
            f"Rapport d'inspection — "
            f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}  |  "
            f"Page {doc.page}"
        )
        canvas.drawCentredString(self.PAGE_W / 2, 10 * mm, footer_text)

        canvas.setStrokeColor(C_GREY_MID)
        canvas.setLineWidth(0.4)
        canvas.line(self.MARGIN, 13 * mm, self.PAGE_W - self.MARGIN, 13 * mm)
        canvas.restoreState()

    # ------------------------------------------------------------------
    # Point d'entrée principal
    # ------------------------------------------------------------------
    def generate(
        self,
        output_path,
        measurement=None,
        stl_comparison=None,
        calibration_result=None,
        working_distance_mm=300.0,
        piece_name="—",
        model_name="YOLOv8-seg",
        operator="Station automatique",
    ):
        """
        Génère le rapport PDF complet.

        Paramètres :
            output_path        : chemin du fichier PDF à créer
            measurement        : DimensionMeasurement (peut être None)
            stl_comparison     : STLComparisonResult (peut être None)
            calibration_result : CalibrationResult (peut être None)
            working_distance_mm: distance caméra-pièce en mm
            piece_name         : nom de la pièce inspectée
            model_name         : nom du modèle IA utilisé
            operator           : nom de l'opérateur ou "Station automatique"
        """
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            leftMargin=self.MARGIN,
            rightMargin=self.MARGIN,
            topMargin=self.MARGIN,
            bottomMargin=self.MARGIN + 6 * mm,
            title="Rapport d'inspection — Pièce imprimée 3D",
            author="Système d'inspection automatique",
            subject="Inspection dimensionnelle post-impression 3D",
        )

        # ── Données de session ───────────────────────────────────────────
        rms_str = "—"
        if calibration_result:
            rms_str = f"{calibration_result.overall_rms_error:.4f} px"
        elif measurement and measurement.confidence:
            rms_str = "—"

        session_info = {
            "datetime": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "piece_name": piece_name if piece_name and piece_name != "—" else "Inconnue",
            "operator": operator,
            "model_name": model_name,
            "working_distance_mm": working_distance_mm,
            "rms_calib": rms_str,
        }

        # ── Construction du rapport ──────────────────────────────────────
        story = []

        # En-tête
        story.extend(self._build_header(session_info))

        # Section 1 — Calibration
        calib_data = {}
        if calibration_result:
            cm_ = calibration_result.camera_matrix
            dc  = calibration_result.dist_coeffs.flatten().tolist()
            calib_data = {
                "rms":         calibration_result.overall_rms_error,
                "fx":          cm_[0, 0],
                "fy":          cm_[1, 1],
                "cx":          cm_[0, 2],
                "cy":          cm_[1, 2],
                "dist_coeffs": dc,
                "n_images":    len(calibration_result.used_image_names),
            }
        else:
            # Essayer de charger depuis le YAML sur disque
            try:
                from calibration_tab import DEFAULT_CALIBRATION_PATH
                import cv2
                if os.path.exists(DEFAULT_CALIBRATION_PATH):
                    fs = cv2.FileStorage(DEFAULT_CALIBRATION_PATH, cv2.FILE_STORAGE_READ)
                    cm_ = fs.getNode("camera_matrix").mat()
                    rms_v = fs.getNode("rms_error").real()
                    n_img_node = fs.getNode("n_images")
                    n_img = int(n_img_node.real()) if not n_img_node.empty() else "—"
                    dc_node = fs.getNode("dist_coeffs")
                    dc = dc_node.mat().flatten().tolist() if not dc_node.empty() else []
                    fs.release()
                    if cm_ is not None:
                        calib_data = {
                            "rms":         rms_v,
                            "fx":          cm_[0, 0],
                            "fy":          cm_[1, 1],
                            "cx":          cm_[0, 2],
                            "cy":          cm_[1, 2],
                            "dist_coeffs": dc,
                            "n_images":    n_img,
                        }
            except Exception:
                pass

        story.extend(self._build_calibration_section(calib_data))
        story.append(Spacer(1, 4 * mm))

        # Section 2 — Mesures dimensionnelles
        story.extend(self._build_measurement_section(measurement, stl_comparison))
        story.append(Spacer(1, 4 * mm))

        # Section 3 — Paramètres d'impression 3D (nouvelle page)
        story.append(PageBreak())
        story.extend(self._build_print_params_section())

        # ── Génération ──────────────────────────────────────────────────
        doc.build(story, onFirstPage=self._footer_func, onLaterPages=self._footer_func)
        return output_path
