import os
import time
import hashlib
from typing import Optional, Dict, Any
from config import settings

def calculate_sha256(filepath: str) -> str:
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest()

def upload_to_internet_archive(
    warc_path: str,
    volunteer: str,
    chunk_id: Optional[int] = None,
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    delete_after_upload: bool = True
) -> Dict[str, Any]:
    """
    Wysyła plik WARC do Internet Archive z wymaganymi metadanymi (mediatype:web)
    i opcjonalnie usuwa lokalną kopię po weryfikacji sumy kontrolnej.
    """
    if not os.path.exists(warc_path):
        return {"success": False, "error": f"Plik {warc_path} nie istnieje."}

    acc_key = access_key or settings.IA_ACCESS_KEY
    sec_key = secret_key or settings.IA_SECRET_KEY

    if not acc_key or not sec_key:
        return {
            "success": False,
            "error": "Brak kluczy IA_ACCESS_KEY / IA_SECRET_KEY. Zapisano lokalnie w ./warcs/"
        }

    import internetarchive as ia

    timestamp = time.strftime("%Y%m%d%H%M%S")
    clean_volunteer = "".join(c for c in volunteer.lower() if c.isalnum() or c in ("-", "_")) or "anon"
    chunk_str = f"chunk{chunk_id:05d}" if chunk_id is not None else "part"
    identifier = f"zapytaj_onet_{clean_volunteer}_{chunk_str}_{timestamp}"

    metadata = {
        "mediatype": "web",
        "collection": "opensource",
        "title": f"Zapytaj Onet Archive - {chunk_str} ({clean_volunteer})",
        "creator": f"Community Archiver ({clean_volunteer})",
        "subject": "zapytaj;zapytaj.onet.pl;archiveteam;polish-qa;warc",
        "description": "Zrzut stron serwisu Zapytaj Onet (zapytaj.onet.pl) wykonany przed wyłączeniem serwisu we wrześniu 2026 r.",
        "date": time.strftime("%Y-%m-%d")
    }

    print(f"[IA Uploader] Wysyłanie {os.path.basename(warc_path)} do Internet Archive (ID: {identifier})...")
    try:
        res = ia.upload(
            identifier=identifier,
            files=[warc_path],
            metadata=metadata,
            access_key=acc_key,
            secret_key=sec_key,
            verbose=True,
            verify=True,
            checksum=True,
            delete=delete_after_upload,
            retries=5
        )
        print(f"[IA Uploader] Sukces! https://archive.org/details/{identifier}")
        return {
            "success": True,
            "identifier": identifier,
            "url": f"https://archive.org/details/{identifier}"
        }
    except Exception as e:
        print(f"[IA Uploader] Błąd wysyłania do Internet Archive: {e}")
        return {
            "success": False,
            "error": str(e)
        }
