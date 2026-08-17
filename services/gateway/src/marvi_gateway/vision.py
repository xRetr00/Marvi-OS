"""Local vision: who is here, and who was here while you were out.

Design notes, since this deliberately diverges from the room sidecar's pipeline
rather than copying it:

* **Inference is motion-gated.** The sidecar runs a continuous analysis loop; a
  camera pointed at an empty room burns CPU forever to learn nothing. Here a
  cheap frame difference decides whether the expensive model runs at all, which
  is the same cheap-signals-first escalation `REAL-AGENCY.md` already asks for.
* **Everything runs on the CPU.** The voice stack already holds 4.245 GiB and
  `AGENTS.md` requires 2 GB of headroom, so vision must not compete for VRAM.
  buffalo_l on CPU measured 124 ms per 640x480 frame, which is far quicker than
  the motion gate will ever ask for it.
* **Unknown faces are compared against the owner first.** A face is only a
  visitor once it has failed to match the enrolled owner, so a bad angle on the
  owner does not manufacture a stranger.
* **Visitors are held, not announced.** Telling someone about a visitor while
  they are out is useless and slightly alarming. Sightings queue up with a
  cropped thumbnail and a timestamp, and surface when the owner is home.

Camera work is isolated behind `VisionService` so the matching, queueing, and
reporting logic can be tested without a camera or a model.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OWNER_THRESHOLD = 0.42
KNOWN_THRESHOLD = 0.38
PENDING_SIMILARITY = 0.45
MOTION_THRESHOLD = 6.0
MAX_PENDING = 40
DETECT_SIZE = (640, 640)

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE,
    owner INTEGER NOT NULL DEFAULT 0,
    at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    vector    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sightings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    identity  TEXT NOT NULL,
    status    TEXT NOT NULL,
    score     REAL NOT NULL DEFAULT 0,
    thumbnail TEXT,
    reported  INTEGER NOT NULL DEFAULT 0,
    vector    TEXT
);
CREATE INDEX IF NOT EXISTS sightings_unreported ON sightings(reported, status);
"""


def default_vision_dir() -> Path:
    configured = os.environ.get("MARVI_VISION_DIR")
    if configured:
        return Path(configured)
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    from .paths import vision_dir as resolved

    return resolved()


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    ln = sum(a * a for a in left) ** 0.5
    rn = sum(b * b for b in right) ** 0.5
    return 0.0 if ln == 0 or rn == 0 else dot / (ln * rn)


class FaceLibrary:
    """Who Marvi knows, who it has seen, and who is waiting to be identified."""

    def __init__(self, directory: Path | None = None) -> None:
        self.dir = directory or default_vision_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "faces").mkdir(exist_ok=True)
        self._db = sqlite3.connect(self.dir / "faces.sqlite3", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # -- enrolment ----------------------------------------------------------

    def enroll(self, name: str, embeddings: list[list[float]], owner: bool = False) -> dict[str, Any]:
        clean = name.strip()[:80]
        if not clean:
            raise ValueError("a person needs a name")
        if not embeddings:
            raise ValueError("a person needs at least one face sample")
        if owner:
            # Exactly one owner: the whole visitor rule is "not the owner".
            self._db.execute("UPDATE people SET owner = 0")
        row = self._db.execute("SELECT id FROM people WHERE name = ?", (clean,)).fetchone()
        if row:
            person_id = int(row["id"])
            self._db.execute("UPDATE people SET owner = ? WHERE id = ?", (1 if owner else 0, person_id))
        else:
            cursor = self._db.execute(
                "INSERT INTO people (name, owner, at) VALUES (?, ?, ?)",
                (clean, 1 if owner else 0, datetime.now(UTC).isoformat()),
            )
            person_id = int(cursor.lastrowid or 0)
        self._db.executemany(
            "INSERT INTO embeddings (person_id, vector) VALUES (?, ?)",
            [(person_id, json.dumps(list(map(float, e)))) for e in embeddings],
        )
        self._db.commit()
        return {"name": clean, "owner": owner, "samples": len(embeddings)}

    def people(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT p.name, p.owner, p.at, COUNT(e.id) AS samples FROM people p"
            " LEFT JOIN embeddings e ON e.person_id = p.id GROUP BY p.id ORDER BY p.owner DESC, p.name"
        ).fetchall()
        return [
            {"name": r["name"], "owner": bool(r["owner"]), "samples": int(r["samples"]), "at": r["at"]}
            for r in rows
        ]

    def owner_name(self) -> str | None:
        row = self._db.execute("SELECT name FROM people WHERE owner = 1 LIMIT 1").fetchone()
        return row["name"] if row else None

    def forget_person(self, name: str) -> bool:
        self._db.execute("PRAGMA foreign_keys = ON")
        cursor = self._db.execute("DELETE FROM people WHERE name = ? COLLATE NOCASE", (name.strip(),))
        self._db.commit()
        return cursor.rowcount > 0

    # -- matching -----------------------------------------------------------

    def match(self, embedding: list[float]) -> dict[str, Any]:
        """Owner first, then anyone else known, then unknown."""
        rows = self._db.execute(
            "SELECT p.name, p.owner, e.vector FROM embeddings e JOIN people p ON p.id = e.person_id"
        ).fetchall()
        best_name, best_score, best_owner = "", 0.0, False
        for row in rows:
            score = cosine(embedding, json.loads(row["vector"]))
            if score > best_score:
                best_name, best_score, best_owner = row["name"], score, bool(row["owner"])

        if best_owner and best_score >= OWNER_THRESHOLD:
            return {"identity": best_name, "status": "owner", "score": round(best_score, 4)}
        if best_name and best_score >= KNOWN_THRESHOLD:
            return {"identity": best_name, "status": "known", "score": round(best_score, 4)}
        return {"identity": "unknown", "status": "unknown", "score": round(best_score, 4)}

    # -- sightings ----------------------------------------------------------

    def record_sighting(
        self,
        identity: str,
        status: str,
        score: float,
        thumbnail: str | None = None,
        embedding: list[float] | None = None,
        now: datetime | None = None,
    ) -> int | None:
        """Log a face. Unknown faces that look like one already queued are
        folded into it, so one visitor lingering is one entry, not fifty."""
        if status == "unknown" and embedding is not None and self._similar_pending(embedding):
            return None
        cursor = self._db.execute(
            "INSERT INTO sightings (at, identity, status, score, thumbnail, reported, vector)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (now or datetime.now(UTC)).isoformat(),
                identity,
                status,
                float(score),
                thumbnail,
                0 if status == "unknown" else 1,
                json.dumps(embedding) if embedding is not None else None,
            ),
        )
        self._db.commit()
        self._trim()
        return int(cursor.lastrowid or 0)

    def _similar_pending(self, embedding: list[float]) -> bool:
        rows = self._db.execute(
            "SELECT vector FROM sightings WHERE status = 'unknown' AND reported = 0"
            " AND vector IS NOT NULL ORDER BY id DESC LIMIT ?",
            (MAX_PENDING,),
        ).fetchall()
        return any(cosine(embedding, json.loads(r["vector"])) >= PENDING_SIMILARITY for r in rows)

    def _trim(self) -> None:
        self._db.execute(
            "DELETE FROM sightings WHERE status = 'unknown' AND reported = 0 AND id NOT IN"
            " (SELECT id FROM sightings WHERE status = 'unknown' AND reported = 0"
            "  ORDER BY id DESC LIMIT ?)",
            (MAX_PENDING,),
        )
        self._db.commit()

    def unreported_visitors(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT id, at, identity, score, thumbnail FROM sightings"
            " WHERE status = 'unknown' AND reported = 0 ORDER BY id"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "at": r["at"],
                "date": r["at"][:10],
                "time": r["at"][11:19],
                "identity": r["identity"],
                "thumbnail": r["thumbnail"],
            }
            for r in rows
        ]

    def mark_reported(self, ids: list[int] | None = None) -> int:
        if ids:
            self._db.executemany(
                "UPDATE sightings SET reported = 1 WHERE id = ?", [(i,) for i in ids]
            )
            count = len(ids)
        else:
            cursor = self._db.execute(
                "UPDATE sightings SET reported = 1 WHERE status = 'unknown' AND reported = 0"
            )
            count = cursor.rowcount
        self._db.commit()
        return count

    def recent_sightings(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT id, at, identity, status, score, thumbnail FROM sightings"
            " ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- approval -----------------------------------------------------------

    def approve(self, sighting_id: int, name: str, owner: bool = False) -> dict[str, Any]:
        """Give a queued unknown face a name, which enrols it for next time."""
        row = self._db.execute(
            "SELECT vector FROM sightings WHERE id = ?", (sighting_id,)
        ).fetchone()
        if row is None or not row["vector"]:
            raise ValueError(f"no stored face for sighting {sighting_id}")
        result = self.enroll(name, [json.loads(row["vector"])], owner=owner)
        self._db.execute(
            "UPDATE sightings SET identity = ?, status = ?, reported = 1 WHERE id = ?",
            (name.strip()[:80], "owner" if owner else "known", sighting_id),
        )
        self._db.commit()
        return result

    def reject(self, sighting_id: int) -> bool:
        cursor = self._db.execute("DELETE FROM sightings WHERE id = ?", (sighting_id,))
        self._db.commit()
        return cursor.rowcount > 0


# -- camera ------------------------------------------------------------------


def frame_motion(previous: Any, current: Any) -> float:
    """Mean absolute difference between two greyscale frames."""
    import numpy as np

    if previous is None or current is None:
        return 100.0
    if previous.shape != current.shape:
        return 100.0
    return float(np.mean(np.abs(current.astype("int16") - previous.astype("int16"))))


class VisionService:
    """Owns the camera and the model. Everything expensive is gated on motion."""

    def __init__(
        self,
        library: FaceLibrary | None = None,
        camera_index: int | None = None,
        analyzer: Any = None,
    ) -> None:
        self.library = library or FaceLibrary()
        self.camera_index = (
            camera_index if camera_index is not None
            else int(os.environ.get("MARVI_CAMERA_INDEX", "0"))
        )
        self._analyzer = analyzer

    def available(self) -> bool:
        return os.environ.get("MARVI_VISION", "").strip().lower() in ("1", "true", "on", "yes")

    def _model(self) -> Any:
        if self._analyzer is None:
            from insightface.app import FaceAnalysis

            # CPU on purpose: the GPU budget belongs to the voice stack.
            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=-1, det_size=DETECT_SIZE)
            self._analyzer = app
        return self._analyzer

    def _thumbnail(self, frame: Any, box: Any, sighting_at: str) -> str | None:
        """Crop the face so a visitor report can actually show a face."""
        try:
            import cv2

            x1, y1, x2, y2 = (max(0, int(v)) for v in box[:4])
            pad = int(0.25 * max(1, x2 - x1))
            crop = frame[max(0, y1 - pad) : y2 + pad, max(0, x1 - pad) : x2 + pad]
            if crop.size == 0:
                return None
            name = f"{sighting_at.replace(':', '-')}-{x1}-{y1}.jpg"
            path = self.library.dir / "faces" / name
            cv2.imwrite(str(path), crop)
            return str(path)
        except Exception:
            return None

    def observe(self, seconds: float = 3.0) -> dict[str, Any]:
        """Look for a few seconds. Runs the model only when the frame changes."""
        import cv2

        # Warm the model before the clock starts. Loading buffalo_l takes ~9s,
        # and doing it inside the loop burns the whole observation window on
        # the first analysed frame.
        self._model()

        capture = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            return {"ok": False, "error": f"camera {self.camera_index} unavailable", "faces": []}

        seen: list[dict[str, Any]] = []
        analysed = frames = 0
        previous = None
        deadline = datetime.now(UTC).timestamp() + max(0.5, min(seconds, 20.0))
        try:
            while datetime.now(UTC).timestamp() < deadline:
                ok, frame = capture.read()
                if not ok:
                    break
                frames += 1
                grey = cv2.cvtColor(cv2.resize(frame, (160, 120)), cv2.COLOR_BGR2GRAY)
                motion = frame_motion(previous, grey)
                previous = grey
                if motion < MOTION_THRESHOLD:
                    continue  # nothing changed; do not pay for inference

                analysed += 1
                for face in self._model().get(frame):
                    embedding = [float(v) for v in face.normed_embedding]
                    verdict = self.library.match(embedding)
                    at = datetime.now(UTC).isoformat()
                    thumb = self._thumbnail(frame, face.bbox, at)
                    sighting = self.library.record_sighting(
                        verdict["identity"], verdict["status"], verdict["score"], thumb, embedding
                    )
                    if sighting is not None:
                        seen.append({**verdict, "at": at, "thumbnail": thumb, "id": sighting})
        finally:
            capture.release()

        return {
            "ok": True,
            "frames": frames,
            "analysed": analysed,
            "skipped_by_motion_gate": frames - analysed,
            "faces": seen,
        }

    def enroll_owner(self, name: str, seconds: float = 4.0) -> dict[str, Any]:
        """Capture a few samples of whoever is in front of the camera."""
        import cv2

        self._model()
        capture = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            return {"ok": False, "error": f"camera {self.camera_index} unavailable"}
        samples: list[list[float]] = []
        deadline = datetime.now(UTC).timestamp() + max(1.0, min(seconds, 20.0))
        try:
            while datetime.now(UTC).timestamp() < deadline and len(samples) < 8:
                ok, frame = capture.read()
                if not ok:
                    break
                faces = self._model().get(frame)
                if len(faces) == 1:
                    samples.append([float(v) for v in faces[0].normed_embedding])
        finally:
            capture.release()

        if not samples:
            return {"ok": False, "error": "no single clear face was visible"}
        return {"ok": True, **self.library.enroll(name, samples, owner=True)}


def register_vision_tools(registry, service: VisionService) -> None:
    from .tools import ToolSpec

    def vision_observe(seconds: int = 3) -> dict[str, Any]:
        return service.observe(float(seconds))

    def vision_describe() -> dict[str, Any]:
        from .describe import describer_from_env

        describer = describer_from_env()
        if describer is None:
            return {
                "available": False,
                "reason": "No vision model configured; set MARVI_VLM_BASE_URL and MARVI_VLM_MODEL.",
            }
        import cv2

        capture = cv2.VideoCapture(service.camera_index, cv2.CAP_DSHOW)
        try:
            ok, frame = capture.read()
        finally:
            capture.release()
        if not ok:
            return {"available": True, "error": "no frame available"}
        return describer.describe(frame)

    def vision_people() -> dict[str, Any]:
        return {"people": service.library.people(), "owner": service.library.owner_name()}

    def vision_visitors() -> dict[str, Any]:
        return {"visitors": service.library.unreported_visitors()}

    def vision_enroll_owner(name: str) -> dict[str, Any]:
        return service.enroll_owner(name)

    def vision_approve(sighting_id: int, name: str) -> dict[str, Any]:
        return service.library.approve(sighting_id, name)

    def vision_reject(sighting_id: int) -> dict[str, Any]:
        return {"rejected": service.library.reject(sighting_id)}

    for spec in (
        ToolSpec(name="vision_observe", description="Look through the camera",
                 arguments={}, optional={"seconds": int}, sensitive=False, handler=vision_observe),
        ToolSpec(name="vision_describe", description="Describe what the camera sees",
                 arguments={}, sensitive=False, handler=vision_describe),
        ToolSpec(name="vision_people", description="Read who Marvi recognises",
                 arguments={}, sensitive=False, handler=vision_people),
        ToolSpec(name="vision_visitors", description="Read unreported visitor sightings",
                 arguments={}, sensitive=False, handler=vision_visitors),
        # Enrolment and approval change who Marvi trusts on sight, so they ask.
        ToolSpec(name="vision_enroll_owner", description="Enrol the owner's face",
                 arguments={"name": str}, sensitive=True, handler=vision_enroll_owner),
        ToolSpec(name="vision_approve", description="Name an unknown face and remember it",
                 arguments={"sighting_id": int, "name": str}, sensitive=True, handler=vision_approve),
        ToolSpec(name="vision_reject", description="Discard an unknown face sighting",
                 arguments={"sighting_id": int}, sensitive=True, handler=vision_reject),
    ):
        registry.register(spec)
