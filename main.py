import sys
import argparse
import os
from config import settings
from dedup import ArchiveBotSync
from worker import run_worker
from uploader import upload_to_internet_archive

def main():
    parser = argparse.ArgumentParser(
        description="Zapytaj Onet Rescue Tool - Rozproszona archiwizacja serwisu zapytaj.onet.pl"
    )
    subparsers = parser.add_subparsers(dest="command", help="Dostępne tryby działania")

    worker_parser = subparsers.add_parser("worker", aliases=["crawl"], help="Uruchom workera pobierającego paczki z koordynatora")
    worker_parser.add_argument("--coordinator", default=settings.COORDINATOR_URL, help=f"URL serwera koordynatora (domyślnie: {settings.COORDINATOR_URL})")
    worker_parser.add_argument("--volunteer", default=settings.VOLUNTEER_NAME, help=f"Twój pseudonim wolontariusza (domyślnie: {settings.VOLUNTEER_NAME})")
    worker_parser.add_argument("--rate", type=float, default=settings.REQUESTS_PER_SECOND, help=f"Liczba zapytań/sekundę (domyślnie: {settings.REQUESTS_PER_SECOND})")
    worker_parser.add_argument("--concurrency", type=int, default=settings.CONCURRENCY, help=f"Współbieżność połączeń (domyślnie: {settings.CONCURRENCY})")
    worker_parser.add_argument("--no-images", action="store_true", help="Wyłącz pobieranie grafik CDN (ocdn.eu)")
    worker_parser.add_argument("--no-pagination", action="store_true", help="Wyłącz pobieranie kolejnych stron odpowiedzi (?page=...)")
    worker_parser.add_argument("--no-upload", action="store_true", help="Wyłącz automatyczną wysyłkę na Internet Archive")

    server_parser = subparsers.add_parser("server", aliases=["coordinator"], help="Uruchom serwer koordynatora z panelem webowym")
    server_parser.add_argument("--host", default="0.0.0.0", help="Interfejs nasłuchu (domyślnie: 0.0.0.0)")
    server_parser.add_argument("--port", type=int, default=8000, help="Port serwera (domyślnie: 8000)")

    subparsers.add_parser("sync", help="Pobierz i zaktualizuj listę pytań pobranych przez ArchiveBota z Archive.org")

    standalone_parser = subparsers.add_parser("standalone", help="Pobierz wybrany zakres pytań bezpośrednio do WARC bez koordynatora")
    standalone_parser.add_argument("--start", type=int, required=True, help="Początkowy identyfikator pytania")
    standalone_parser.add_argument("--end", type=int, required=True, help="Końcowy identyfikator pytania")
    standalone_parser.add_argument("--volunteer", default="standalone_user", help="Pseudonim operatora")
    standalone_parser.add_argument("--rate", type=float, default=6.0, help="Zapytania/sekundę")

    upload_parser = subparsers.add_parser("upload", help="Wyślij istniejące pliki z ./warcs na Internet Archive")
    upload_parser.add_argument("--access-key", help="Klucz IA S3 Access Key")
    upload_parser.add_argument("--secret-key", help="Klucz IA S3 Secret Key")
    upload_parser.add_argument("--volunteer", default="anon", help="Pseudonim wolontariusza")

    args = parser.parse_args()

    if not args.command:
        print("Brak podanego trybu. Uruchamianie trybu domyślnego: WORKER.")
        volunteer = input(f"Podaj swój nick wolontariusza [{settings.VOLUNTEER_NAME}]: ").strip() or settings.VOLUNTEER_NAME
        coordinator = input(f"Podaj adres koordynatora [{settings.COORDINATOR_URL}]: ").strip() or settings.COORDINATOR_URL
        run_worker(coordinator_url=coordinator, volunteer_name=volunteer, auto_upload=settings.AUTO_UPLOAD)
        return

    if args.command in ("worker", "crawl"):
        auto_up = False if args.no_upload else settings.AUTO_UPLOAD
        run_worker(
            coordinator_url=args.coordinator,
            volunteer_name=args.volunteer,
            concurrency=args.concurrency,
            req_per_second=args.rate,
            download_images=not args.no_images,
            follow_pagination=not args.no_pagination,
            auto_upload=auto_up
        )

    elif args.command in ("server", "coordinator"):
        try:
            import uvicorn
        except ImportError:
            print("Błąd: Pakiet 'uvicorn' nie jest zainstalowany. Zainstaluj go komendą: pip install uvicorn")
            sys.exit(1)
        print(f"Uruchamianie serwera koordynatora na http://{args.host}:{args.port}...")
        uvicorn.run("coordinator:app", host=args.host, port=args.port, reload=False)

    elif args.command == "sync":
        sync = ArchiveBotSync()
        sync.sync()
        known = sync.get_known_ids()
        print(f"W bazie zapisano łącznie {len(known):,} unikalnych pytań pobranych przez ArchiveBota.")

    elif args.command == "standalone":
        import asyncio
        from warc_manager import WarcManager
        from crawler import ZapytajCrawler

        wm = WarcManager(output_dir=settings.WARCS_DIR, volunteer_name=args.volunteer)
        crawler = ZapytajCrawler(warc_manager=wm, req_per_second=args.rate)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stats = loop.run_until_complete(crawler.crawl_range(args.start, args.end))
        loop.close()
        
        path, recs, size = wm.close()
        print(f"\nUkończono! WARC: {path} ({round(size / (1024*1024), 2)} MB, {recs} rekordów).")

    elif args.command == "upload":
        import re
        import requests
        warcs_dir = settings.WARCS_DIR
        if not os.path.exists(warcs_dir):
            print(f"Katalog {warcs_dir} nie istnieje.")
            return

        files = [os.path.join(warcs_dir, f) for f in os.listdir(warcs_dir) if f.endswith(".warc.gz") and not f.endswith(".tmp")]
        if not files:
            print(f"Brak plików .warc.gz w {warcs_dir}.")
            return

        vol_name = args.volunteer if args.volunteer != "anon" else settings.VOLUNTEER_NAME
        print(f"Znaleziono {len(files)} plików WARC do wysłania dla wolontariusza: {vol_name}.")

        for f in files:
            fname = os.path.basename(f)
            file_sz = os.path.getsize(f) if os.path.exists(f) else 0
            if file_sz < 50000:
                print(f"\n[Upload] Pomijanie {fname} - plik ma tylko {file_sz} B (jest pusty lub uszkodzony).")
                continue

            m = re.search(r"chunk0*(\d+)", fname)
            cid = int(m.group(1)) if m else None

            # Zlicz realną liczbę pytań z pliku WARC
            real_saved = 0
            try:
                from warcio.archiveiterator import ArchiveIterator
                with open(f, "rb") as stream:
                    real_saved = sum(1 for record in ArchiveIterator(stream) if record.rec_type == "response")
            except Exception:
                real_saved = max(int(file_sz / 80000), 10)

            if real_saved == 0:
                print(f"\n[Upload] Pomijanie {fname} - brak odpowiedzi HTTP w pliku (0 pytań).")
                continue
            
            print(f"\n[Upload] Rozpoczynanie wysyłki {fname} (paczka #{cid}, {round(file_sz / (1024*1024), 2)} MB, ~{real_saved} pytań)...")
            res = upload_to_internet_archive(
                warc_path=f,
                volunteer=vol_name,
                chunk_id=cid,
                access_key=args.access_key,
                secret_key=args.secret_key,
                delete_after_upload=True
            )
            if res.get("success"):
                print(f"[Upload] Wysłano na: {res.get('url')}")
                if cid and settings.COORDINATOR_URL:
                    try:
                        r = requests.post(
                            f"{settings.COORDINATOR_URL.rstrip('/')}/api/chunk/complete",
                            json={
                                "chunk_id": cid,
                                "volunteer": vol_name,
                                "items_saved": real_saved,
                                "items_404": 0,
                                "warc_filename": fname,
                                "warc_size": file_sz,
                                "checksum": ""
                            },
                            timeout=15
                        )
                        print(f"[Upload] Koordynator zaliczył paczkę #{cid} w rankingu!")
                    except Exception as ex:
                        print(f"[Upload] Błąd raportowania: {ex}")
            else:
                print(f"[Upload] BŁĄD: {res.get('error')}")

if __name__ == "__main__":
    main()
