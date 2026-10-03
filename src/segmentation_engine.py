"""
Module de segmentation et mesure dimensionnelle (Partie 2 du pipeline).

Deux responsabilités séparées, comme pour la Partie 1 (logique métier
indépendante de l'UI Qt) :

    SegmentationEngine
        Charge un modèle YOLOv8-seg (.pt) et produit un masque de
        segmentation de la pièce détectée. Tant qu'aucun modèle .pt n'est
        fourni, fonctionne en mode "stub" : le bouton Activer la segmentation
        reste utilisable dans l'UI, mais signale clairement qu'aucun modèle
        n'est chargé plutôt que de planter.

    DimensionAnalyzer
        À partir d'un masque binaire (qu'il vienne de YOLOv8-seg ou d'un
        autre moyen), extrait le contour, calcule les dimensions réelles en
        mm via une échelle mm/pixel fournie (issue de la calibration ChArUco
        de la Partie 1), et produit l'image annotée.
"""

import os
import json
import csv
from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Segmentation (YOLOv8-seg)
# ---------------------------------------------------------------------------

@dataclass
class SegmentationResult:
    """Résultat d'une inférence de segmentation sur une image."""

    mask: np.ndarray            # masque binaire uint8 (0/255), taille image
    confidence: float            # confiance du modèle pour la détection retenue
    class_name: str              # nom de la classe détectée
    bbox: tuple                  # (x, y, w, h) en pixels


class SegmentationEngine:
    """
    Encapsule le modèle YOLOv8-seg.

    Usage prévu une fois le modèle .pt disponible :
        engine = SegmentationEngine()
        engine.load_model("/chemin/vers/mon_modele.pt")
        result = engine.segment(frame_bgr)   # None si rien détecté

    Tant qu'aucun modèle n'est chargé (`is_loaded` False), `segment()`
    retourne toujours None — l'UI doit vérifier `is_loaded` avant d'activer
    réellement le traitement, et afficher un message clair sinon plutôt que
    de planter ou de simuler un faux résultat.
    """

    def __init__(self):
        self.model = None
        self.model_path = None
        self.confidence_threshold = 0.5

    @property
    def is_loaded(self):
        return self.model is not None

    def load_model(self, model_path):
        """
        Charge un modèle YOLOv8-seg depuis un fichier .pt.

        Lève FileNotFoundError si le chemin n'existe pas, ou ImportError
        si le paquet `ultralytics` n'est pas installé (volontairement : on
        ne veut pas dépendre d'ultralytics tant qu'aucun modèle n'est requis,
        donc l'import se fait ici, pas en haut du fichier).
        """
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Modèle introuvable : {model_path}")

        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise ImportError(
                "Le paquet 'ultralytics' n'est pas installé. "
                "Installez-le avec : pip install ultralytics"
            ) from e

        self.model = YOLO(model_path)
        self.model_path = model_path

    def unload_model(self):
        self.model = None
        self.model_path = None

    def segment(self, frame_bgr):
        """
        Exécute la segmentation sur une image.

        Retourne un SegmentationResult pour la détection la plus confiante,
        ou None si aucun modèle n'est chargé ou si rien n'est détecté
        au-dessus du seuil de confiance.
        """
        if not self.is_loaded:
            return None

        results = self.model.predict(
            frame_bgr, conf=self.confidence_threshold, verbose=False
        )
        if not results or results[0].masks is None or len(results[0].masks) == 0:
            return None

        r = results[0]
        # Retient la détection la plus confiante (cas d'une seule pièce
        # inspectée à la fois sur la station fixe).
        confidences = r.boxes.conf.cpu().numpy()
        best_idx = int(np.argmax(confidences))

        mask_data = r.masks.data[best_idx].cpu().numpy()
        h, w = frame_bgr.shape[:2]
        mask = cv2.resize(mask_data, (w, h), interpolation=cv2.INTER_NEAREST)
        mask = (mask > 0.5).astype(np.uint8) * 255

        class_id = int(r.boxes.cls[best_idx].item())
        class_name = self.model.names.get(class_id, str(class_id))

        x1, y1, x2, y2 = r.boxes.xyxy[best_idx].cpu().numpy()
        bbox = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))

        return SegmentationResult(
            mask=mask,
            confidence=float(confidences[best_idx]),
            class_name=class_name,
            bbox=bbox,
        )


# ---------------------------------------------------------------------------
# Analyse dimensionnelle (findContours + échelle mm/pixel)
# ---------------------------------------------------------------------------

@dataclass
class DimensionMeasurement:
    """Résultat d'une mesure dimensionnelle sur un masque segmenté."""

    length_mm: float
    width_mm: float
    area_mm2: float
    contour: np.ndarray          # contour OpenCV (pixels), pour overlay
    min_area_rect: tuple         # ((cx,cy),(w,h),angle) en pixels, cv2.minAreaRect
    piece_name: str = ""
    confidence: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self):
        return {
            "piece_name": self.piece_name,
            "confidence": round(self.confidence, 4),
            "length_mm": round(self.length_mm, 3),
            "width_mm": round(self.width_mm, 3),
            "area_mm2": round(self.area_mm2, 3),
            "timestamp": self.timestamp,
        }


class DimensionAnalyzer:
    """
    Calcule les dimensions réelles d'une pièce à partir de son masque de
    segmentation et d'une échelle mm/pixel (issue de la calibration ChArUco).
    """

    def __init__(self, mm_per_pixel=None):
        # Échelle constante : caméra fixe à distance connue (cf. décision
        # produit). Définie via set_scale_from_calibration() ou directement.
        self.mm_per_pixel = mm_per_pixel

    def set_scale(self, mm_per_pixel):
        self.mm_per_pixel = mm_per_pixel

    def set_scale_from_calibration(self, camera_matrix, working_distance_mm):
        """
        Dérive l'échelle mm/pixel à partir de la matrice caméra calibrée
        (Partie 1) et de la distance de travail fixe caméra-pièce.

        Approximation standard pour une caméra perspective : à une distance
        de travail D (mm), un pixel correspond physiquement à D / f (mm),
        où f est la focale en pixels (fx, fy de la matrice caméra). On
        moyenne fx et fy pour limiter l'effet d'un léger non-carré pixel.
        """
        fx = camera_matrix[0, 0]
        fy = camera_matrix[1, 1]
        f_avg = (fx + fy) / 2.0
        self.mm_per_pixel = working_distance_mm / f_avg
        return self.mm_per_pixel

    @property
    def is_calibrated(self):
        return self.mm_per_pixel is not None

    def analyze(self, mask, piece_name="", confidence=0.0):
        """
        Extrait le contour principal du masque et calcule les dimensions.

        Retourne un DimensionMeasurement, ou None si aucun contour
        exploitable n'a été trouvé dans le masque.
        Lève ValueError si l'échelle mm/pixel n'a pas été définie.
        """
        if not self.is_calibrated:
            raise ValueError(
                "Échelle mm/pixel non définie. Appelez set_scale() ou "
                "set_scale_from_calibration() avant analyze()."
            )

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return None

        # Plus grand contour par aire = la pièce (élimine le bruit résiduel
        # du masque, ex: petits îlots de pixels mal segmentés).
        main_contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(main_contour) < 10:
            return None

        # Rectangle orienté minimal : donne longueur/largeur réelles même si
        # la pièce n'est pas alignée avec les axes de l'image.
        rect = cv2.minAreaRect(main_contour)
        (cx, cy), (w_px, h_px), angle = rect

        length_px = max(w_px, h_px)
        width_px = min(w_px, h_px)

        length_mm = length_px * self.mm_per_pixel
        width_mm = width_px * self.mm_per_pixel
        area_px = cv2.contourArea(main_contour)
        area_mm2 = area_px * (self.mm_per_pixel ** 2)

        return DimensionMeasurement(
            length_mm=length_mm,
            width_mm=width_mm,
            area_mm2=area_mm2,
            contour=main_contour,
            min_area_rect=rect,
            piece_name=piece_name,
            confidence=confidence,
        )

    @staticmethod
    def draw_annotations(frame_bgr, measurement, mask=None):
        """
        Dessine le contour, le rectangle englobant orienté, et les valeurs
        de mesure sur une copie de l'image, pour overlay et capture.
        """
        overlay = frame_bgr.copy()

        if mask is not None:
            colored_mask = np.zeros_like(overlay)
            colored_mask[:, :, 1] = mask  # teinte verte semi-transparente
            overlay = cv2.addWeighted(overlay, 1.0, colored_mask, 0.35, 0)

        if measurement is not None:
            cv2.drawContours(overlay, [measurement.contour], -1, (0, 255, 0), 2)

            box = cv2.boxPoints(measurement.min_area_rect)
            box = box.astype(np.int32)
            cv2.drawContours(overlay, [box], -1, (255, 140, 0), 2)

            h, w = overlay.shape[:2]
            cx, cy = measurement.min_area_rect[0]
            text = (
                f"L={measurement.length_mm:.1f}mm  "
                f"l={measurement.width_mm:.1f}mm  "
                f"A={measurement.area_mm2:.0f}mm2"
            )
            (text_w, text_h), _ = cv2.getTextSize(
                text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2
            )
            text_x = int(np.clip(cx - text_w / 2, 5, max(5, w - text_w - 5)))
            text_y = int(np.clip(cy - 20, text_h + 5, h - 5))

            cv2.putText(
                overlay, text, (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA
            )
            cv2.putText(
                overlay, text, (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 100, 0), 1, cv2.LINE_AA
            )

        return overlay


# ---------------------------------------------------------------------------
# Export des mesures (CSV / JSON)
# ---------------------------------------------------------------------------

class MeasurementExporter:
    """Gère l'export d'un historique de mesures en CSV ou JSON."""

    @staticmethod
    def export_csv(measurements, path):
        fieldnames = [
            "piece_name", "confidence", "length_mm", "width_mm",
            "area_mm2", "timestamp",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for m in measurements:
                writer.writerow(m.to_dict())

    @staticmethod
    def export_json(measurements, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                [m.to_dict() for m in measurements], f, indent=2, ensure_ascii=False
            )
