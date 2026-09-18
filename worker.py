import time
import os
import requests
import asyncio
import threading
from typing import Optional
from config import settings
from dedup import ArchiveBotSync
from warc_manager import WarcManager
from crawler import ZapytajCrawler
from uploader import upload_to_internet_archive, calculate_sha256

def run_worker(
    coordinator_url: str = settings.COORDINATOR_URL,
    volunteer_name: str = settings.VOLUNTEER_NAME,
    concurrency: int = settings.CONCURRENCY,
    req_per_second: float = settings.REQUESTS_PER_SECOND,
    download_images: bool = settings.DOWNLOAD_IMAGES,
    follow_pagination: bool = settings.FOLLOW_PAGINATION,
    auto_upload: bool = settings.AUTO_UPLOAD
):
    print("=" * 65)
    print("   ZAPYTAJ ONET COMMUNITY RESCUE - VOLUNTEER WORKER")
    print(f"   Wolontariusz:   {volunteer_name}")
    print(f"   Koordynator:    {coordinator_url}")
    print(f"   Prędkość:       {req_per_second} req/s (współbieżność: {concurrency})")
    print(f"   Auto-Upload IA: {'TAK (Klucze S3 skonfigurowane)' if (settings.IA_ACCESS_KEY and settings.IA_SECRET_KEY) else 'BRAK KLUCZY W .ENV (Tylko zapis lokalny!)'}")
    print("=" * 65)

    sync = ArchiveBotSync()
    known_archivebot_ids = sync.get_known_ids()
    if not known_archivebot_ids:
        print("[Worker] Baza deduplikacji jest pusta. Pobieranie wstępnych indeksów ArchiveBota...")
        sync.sync()
        known_archivebot_ids = sync.get_known_ids()
    print(f"[Worker] Załadowano {len(known_archivebot_ids):,} pytań pobranych przez ArchiveBota (będą pomijane).")

    try:
        while True:
            print(f"\n[Worker] Zgłaszanie do koordynatora po nową paczkę...")
            try:
                r = requests.post(
                    f"{coordinator_url.rstrip('/')}/api/chunk/claim",
                    json={"volunteer": volunteer_name},
                    timeout=15
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                print(f"[Worker] Błąd połączenia z koordynatorem ({coordinator_url}): {e}")
                print("[Worker] Ponowna próba za 10 sekund...")
                time.sleep(10)
                continue

            if data.get("status") == "ALL_DONE":
                print("\n[Worker] Wszystkie paczki serwisu zostały przydzielone lub ukończone.")
                break

            chunk = data.get("chunk")
            if not chunk:
                print(f"[Worker] Nieoczekiwana odpowiedź koordynatora: {data}")
                time.sleep(5)
                continue

            chunk_id = chunk["chunk_id"]
            start_id = chunk["start_id"]
            end_id = chunk["end_id"]
            print(f"\n[Worker] Otrzymano paczkę #{chunk_id}: zakres ID od {start_id} do {end_id} (łącznie: {abs(start_id - end_id) + 1} ID)")

            warc_mgr = WarcManager(
                output_dir=settings.WARCS_DIR,
                volunteer_name=volunteer_name,
                chunk_id=chunk_id
            )

            def send_heartbeat():
                try:
                    requests.post(
                        f"{coordinator_url.rstrip('/')}/api/chunk/heartbeat",
                        json={"chunk_id": chunk_id, "volunteer": volunteer_name},
                        timeout=5
                    )
                except Exception:
                    pass

            crawler = ZapytajCrawler(
                warc_manager=warc_mgr,
                known_archivebot_ids=known_archivebot_ids,
                heartbeat_callback=send_heartbeat,
                concurrency=concurrency,
                req_per_second=req_per_second,
                download_images=download_images,
                follow_pagination=follow_pagination
            )

            stats = asyncio.run(crawler.crawl_range(start_id, end_id))

            warc_path, rec_count, warc_bytes = warc_mgr.close()
            warc_filename = os.path.basename(warc_path)
            mb_size = round(warc_bytes / (1024 * 1024), 2)
            print(f"[Worker] Zamknięto plik WARC: {warc_filename} ({mb_size} MB, {rec_count} rekordów).")

            # Utrzymujemy heartbeat w osobnym wątku podczas hashowania i wysyłania do Internet Archive,
            # aby koordynator nie zrestartował dzierżawy przy wolnym uploadzie (>30 min).
            stop_upload_heartbeat = threading.Event()

            def _upload_heartbeat_loop():
                while not stop_upload_heartbeat.wait(timeout=settings.HEARTBEAT_INTERVAL):
                    send_heartbeat()

            hb_thread = threading.Thread(target=_upload_heartbeat_loop, daemon=True)
            hb_thread.start()

            upload_ok = True
            checksum = ""
            try:
                checksum = calculate_sha256(warc_path) if os.path.exists(warc_path) else ""
                if auto_upload:
                    if settings.IA_ACCESS_KEY and settings.IA_SECRET_KEY:
                        print(f"[Worker] Wysyłanie paczki #{chunk_id} na konto Internet Archive (heartbeat aktywny)...")
                        up_res = upload_to_internet_archive(
                            warc_path,
                            volunteer=volunteer_name,
                            chunk_id=chunk_id,
                            access_key=settings.IA_ACCESS_KEY,
                            secret_key=settings.IA_SECRET_KEY,
                            delete_after_upload=True
                        )
                        if not up_res.get("success"):
                            upload_ok = False
                            print(f"[Worker] BŁĄD UPLOADU DO IA: {up_res.get('error')}")
                            print(f"[Worker] Plik {warc_filename} zachowano w ./warcs/. Paczka #{chunk_id} NIE zostanie oznaczona jako ukończona.")
                    else:
                        print(f"[OSTRZEŻENIE] Brak kluczy IA_ACCESS_KEY / IA_SECRET_KEY w .env.")
                        print(f"[OSTRZEŻENIE] Plik {warc_filename} został zachowany lokalnie w ./warcs/.")
            finally:
                stop_upload_heartbeat.set()
                hb_thread.join(timeout=1.0)

            if upload_ok:
                try:
                    requests.post(
                        f"{coordinator_url.rstrip('/')}/api/chunk/complete",
                        json={
                            "chunk_id": chunk_id,
                            "volunteer": volunteer_name,
                            "items_saved": stats["saved"],
                            "items_404": stats["not_found"],
                            "warc_filename": warc_filename,
                            "warc_size": warc_bytes,
                            "checksum": checksum
                        },
                        timeout=15
                    )
                    print(f"[Worker] Paczka #{chunk_id} pomyślnie rozliczona u koordynatora.")
                except Exception as ex:
                    print(f"[Worker] Błąd raportowania ukończenia do koordynatora: {ex}")

            print(f"[Worker] Przechodzenie do kolejnej paczki...")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[Worker] Przerwano działanie (Ctrl+C).")
