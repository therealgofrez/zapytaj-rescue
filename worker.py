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
    print(f"   Auto-Upload IA: {'TAK (Klucze S3 skonfigurowane)' if (settings.IA_ACCESS_KEY and settings.IA_SECRET_KEY) else 'BRAK KLUCZY W .ENV (Tylko zapis lokalny)'}")
    print("=" * 65)

    sync = ArchiveBotSync()
    known_archivebot_ids = sync.get_known_ids()
    if not known_archivebot_ids:
        print("[Worker] Baza deduplikacji jest pusta. Pobieranie wstępnych indeksów ArchiveBota...")
        sync.sync()
        known_archivebot_ids = sync.get_known_ids()
    print(f"[Worker] Załadowano {len(known_archivebot_ids):,} pytań pobranych przez ArchiveBota (będą pomijane).")

    def process_pending_warcs():
        if not os.path.exists(settings.WARCS_DIR):
            return
        pending = [
            f for f in sorted(os.listdir(settings.WARCS_DIR))
            if f.endswith(".warc.gz") and not f.endswith(".tmp")
        ]
        if not pending:
            return

        print(f"\n[Worker] Znaleziono {len(pending)} plików WARC na dysku w {settings.WARCS_DIR}.")
        if not auto_upload or not (settings.IA_ACCESS_KEY and settings.IA_SECRET_KEY):
            print("[Worker] Auto-upload jest wyłączony lub brak kluczy IA. Pliki pozostają na dysku.")
            return

        import re
        for pf in pending:
            full_p = os.path.join(settings.WARCS_DIR, pf)
            file_sz = os.path.getsize(full_p) if os.path.exists(full_p) else 0
            if file_sz < 50000:
                print(f"[Worker] OSTRZEŻENIE: Plik {pf} ma tylko {file_sz} B (jest pusty lub uszkodzony). Pomijanie wysyłki.")
                continue

            m = re.search(r"chunk0*(\d+)", pf)
            cid = int(m.group(1)) if m else None

            # Zlicz realną liczbę pobranych pytań/odpowiedzi z pliku WARC
            real_saved = 0
            try:
                from warcio.archiveiterator import ArchiveIterator
                with open(full_p, "rb") as stream:
                    real_saved = sum(1 for record in ArchiveIterator(stream) if record.rec_type == "response")
            except Exception:
                real_saved = max(int(file_sz / 80000), 10)

            if real_saved == 0:
                print(f"[Worker] Plik {pf} nie zawiera żadnych rekordów (0 pytań). Pomijanie wysyłki.")
                continue

            print(f"[Worker] Dokańczanie wysyłki zaległej paczki #{cid} ({pf}, {round(file_sz / (1024*1024), 2)} MB, ~{real_saved} pytań)...")
            
            stop_hb = threading.Event()
            def _hb():
                while not stop_hb.wait(timeout=settings.HEARTBEAT_INTERVAL):
                    if cid:
                        try:
                            requests.post(
                                f"{coordinator_url.rstrip('/')}/api/chunk/heartbeat",
                                json={"chunk_id": cid, "volunteer": volunteer_name},
                                timeout=5
                            )
                        except Exception:
                            pass
            th = threading.Thread(target=_hb, daemon=True)
            th.start()

            try:
                res = upload_to_internet_archive(
                    warc_path=full_p,
                    volunteer=volunteer_name,
                    chunk_id=cid,
                    delete_after_upload=True
                )
            finally:
                stop_hb.set()
                th.join(timeout=1.0)

            if res.get("success"):
                print(f"[Worker] Pomyślnie wysłano zaległy plik: {pf}")
                if cid:
                    try:
                        requests.post(
                            f"{coordinator_url.rstrip('/')}/api/chunk/complete",
                            json={
                                "chunk_id": cid,
                                "volunteer": volunteer_name,
                                "items_saved": real_saved,
                                "items_404": 0,
                                "warc_filename": pf,
                                "warc_size": file_sz,
                                "checksum": ""
                            },
                            timeout=15
                        )
                        print(f"[Worker] Zaległa paczka #{cid} została zaakceptowana na serwerze.")
                    except Exception as e:
                        print(f"[Worker] Błąd zgłaszania do koordynatora: {e}")
            else:
                print(f"[Worker] Nie udało się wysłać {pf}: {res.get('error')}")

    process_pending_warcs()

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

            stop_upload_heartbeat = threading.Event()

            def _upload_heartbeat_loop():
                while not stop_upload_heartbeat.wait(timeout=settings.HEARTBEAT_INTERVAL):
                    send_heartbeat()

            hb_thread = threading.Thread(target=_upload_heartbeat_loop, daemon=True)
            hb_thread.start()

            upload_ok = True
            if stats["saved"] == 0 and warc_bytes < 50000:
                print(f"\n[Worker] OSTRZEŻENIE: Paczka #{chunk_id} zakończyła się bez zapisanych pytań (rozmiar {warc_bytes} B).")
                print(f"[Worker] Plik {warc_filename} nie zostanie wysłany ani oznaczony jako ukończony (błąd sieci/WAF).")
                upload_ok = False

            checksum = ""
            try:
                checksum = calculate_sha256(warc_path) if (upload_ok and os.path.exists(warc_path)) else ""
                if auto_upload:
                    if settings.IA_ACCESS_KEY and settings.IA_SECRET_KEY:
                        print(f"[Worker] Wysyłanie paczki #{chunk_id} na konto Internet Archive...")
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
                    print(f"[Worker] Paczka #{chunk_id} została zaakceptowana na serwerze.")
                except Exception as ex:
                    print(f"[Worker] Błąd raportowania ukończenia do koordynatora: {ex}")

            print(f"[Worker] Przechodzenie do kolejnej paczki...")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[Worker] Przerwano działanie (Ctrl+C).")
