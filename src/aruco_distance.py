"""
Calcul de l'échelle mm/pixel via la méthode ratio direct du marqueur ArUco.

    mm_per_pixel = taille_reelle_mm / taille_mesuree_px

Fonctionne sur flux live ET image statique. Aucune calibration requise.
Paramètre clé : MARKER_REAL_SIZE_MM (à ajuster selon ta feuille).
"""
import cv2
import cv2.aruco as aruco
import numpy as np

MARKER_REAL_SIZE_MM = 25.0  # ⚠️ mesurer le côté du carré noir avec une règle


class ArucoScaleEstimator:
    def __init__(self, marker_real_size_mm=MARKER_REAL_SIZE_MM,
                 dictionary_id=aruco.DICT_5X5_1000):
        self.marker_real_size_mm = marker_real_size_mm
        self.dictionary = aruco.getPredefinedDictionary(dictionary_id)
        self.detector = aruco.ArucoDetector(
            self.dictionary, aruco.DetectorParameters()
        )
        self.last_mm_per_px = None
        self.last_n_markers = 0

    def set_marker_size(self, size_mm):
        self.marker_real_size_mm = size_mm

    def _marker_side_px(self, corners_one):
        pts = corners_one.reshape(4, 2)
        return float(np.mean([np.linalg.norm(pts[(i+1)%4]-pts[i]) for i in range(4)]))

    def process(self, frame_bgr):
        """Retourne (mm_per_px, n_markers, overlay)."""
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)
        overlay = frame_bgr.copy()

        if ids is None or len(ids) == 0:
            self._draw(overlay, self.last_mm_per_px, 0, fresh=False)
            return self.last_mm_per_px, 0, overlay

        ratios = [self.marker_real_size_mm / self._marker_side_px(c[0])
                  for c in corners if self._marker_side_px(c[0]) > 1.0]
        if not ratios:
            self._draw(overlay, self.last_mm_per_px, 0, fresh=False)
            return self.last_mm_per_px, 0, overlay

        mm_per_px = float(np.median(ratios))
        self.last_mm_per_px = mm_per_px
        self.last_n_markers = len(ratios)
        aruco.drawDetectedMarkers(overlay, corners, ids, (0, 220, 255))
        self._draw(overlay, mm_per_px, len(ratios), fresh=True)
        return mm_per_px, len(ratios), overlay

    def _draw(self, overlay, mm_per_px, n, fresh=True):
        h = overlay.shape[0]
        if mm_per_px is not None:
            color = (0, 220, 120) if fresh else (160, 160, 160)
            txt = f"Echelle: {mm_per_px:.4f} mm/px  ({n} marqueur{'s' if n!=1 else ''})"
        else:
            color = (80, 80, 200)
            txt = "Echelle: marqueurs non detectes"
        cv2.putText(overlay, txt, (10, h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0,0,0), 3, cv2.LINE_AA)
        cv2.putText(overlay, txt, (10, h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 1, cv2.LINE_AA)
