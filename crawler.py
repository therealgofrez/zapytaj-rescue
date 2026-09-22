import asyncio
import time
from urllib.parse import urljoin
from typing import Set, Optional, Callable, Dict, Any
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from warc_manager import WarcManager
from config import settings

class ZapytajCrawler:
    def __init__(
        self,
        warc_manager: WarcManager,
        known_archivebot_ids: Optional[Set[int]] = None,
        heartbeat_callback: Optional[Callable[[], Any]] = None,
        concurrency: int = 3,
        req_per_second: float = 4.0,
        download_images: bool = True,
        follow_pagination: bool = True
    ):
        self.warc_manager = warc_manager
        self.known_archivebot_ids = known_archivebot_ids or set()
        self.heartbeat_callback = heartbeat_callback
        self.concurrency = max(1, concurrency)
        self.delay_per_worker = self.concurrency / req_per_second if req_per_second > 0 else 0.5
        self.download_images = download_images
        self.follow_pagination = follow_pagination
        
        self.saved_count = 0
        self.not_found_count = 0
        self.skipped_archivebot_count = 0
        self.error_count = 0
        self.processed_count = 0
        self.is_running = False

    async def _heartbeat_worker(self):
        try:
            while self.is_running:
                await asyncio.sleep(settings.HEARTBEAT_INTERVAL)
                if self.heartbeat_callback and self.is_running:
                    try:
                        self.heartbeat_callback()
                    except Exception as e:
                        print(f"[Heartbeat] Błąd: {e}")
        except asyncio.CancelledError:
            pass

    async def _safe_fetch(self, session: AsyncSession, url: str, allow_redirects: bool = False, retries: int = 3):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        for attempt in range(retries):
            try:
                resp = await session.get(url, headers=headers, allow_redirects=allow_redirects, timeout=settings.REQUEST_TIMEOUT)
                if resp.status_code in (429, 504):
                    print(f"[RateLimit] Kod {resp.status_code} na {url}. Odczekanie {settings.BACKOFF_ON_429}s...")
                    await asyncio.sleep(settings.BACKOFF_ON_429)
                    continue
                return resp
            except Exception as e:
                if attempt == retries - 1:
                    return None
                await asyncio.sleep(2)
        return None

    async def _worker_loop(self, queue: asyncio.Queue, session: AsyncSession, total: int, t_start: float):
        while self.is_running:
            try:
                qid = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if queue.empty():
                    break
                continue

            try:
                if qid in self.known_archivebot_ids:
                    self.skipped_archivebot_count += 1
                else:
                    probe_url = f"https://zapytaj.onet.pl/Category/000,000/2,{qid},q.html"
                    resp = await self._safe_fetch(session, probe_url, allow_redirects=False)
                    await asyncio.sleep(self.delay_per_worker)

                    if not resp:
                        self.error_count += 1
                    elif resp.status_code == 404:
                        self.not_found_count += 1
                    elif resp.status_code == 302:
                        self.warc_manager.write_response(probe_url, 302, "Found", dict(resp.headers), resp.content)
                        target_loc = resp.headers.get("Location") or resp.headers.get("location")
                        if target_loc:
                            canonical_url = urljoin("https://zapytaj.onet.pl", target_loc)
                            target_resp = await self._safe_fetch(session, canonical_url, allow_redirects=True)
                            await asyncio.sleep(self.delay_per_worker)

                            if target_resp and target_resp.status_code == 200:
                                self.warc_manager.write_response(canonical_url, 200, "OK", dict(target_resp.headers), target_resp.content)
                                self.saved_count += 1

                                if self.follow_pagination or self.download_images:
                                    await self._fetch_subresources(session, target_resp.text)
                            else:
                                self.error_count += 1
                        else:
                            self.not_found_count += 1
                    elif resp.status_code == 200:
                        self.warc_manager.write_response(probe_url, 200, "OK", dict(resp.headers), resp.content)
                        self.saved_count += 1
                        if self.follow_pagination or self.download_images:
                            await self._fetch_subresources(session, resp.text)
                    elif resp.status_code == 403:
                        if self.error_count % 500 == 0:
                            print(f"[OSTRZEŻENIE] Kod 403 Forbidden od serwera na {probe_url}!")
                        self.error_count += 1
                    else:
                        self.error_count += 1

            except Exception:
                self.error_count += 1
            finally:
                self.processed_count += 1
                queue.task_done()
                if self.processed_count % 100 == 0 or self.processed_count == total:
                    elapsed = max(time.time() - t_start, 0.001)
                    rate = self.processed_count / elapsed
                    print(
                        f"[Postęp] {self.processed_count}/{total} ({self.processed_count/total*100:.1f}%) | "
                        f"Zapisano: {self.saved_count} | 404: {self.not_found_count} | "
                        f"Pominięto (bot): {self.skipped_archivebot_count} | "
                        f"Błędy: {self.error_count} | Prędkość: {rate:.1f} req/s"
                    )

    async def _fetch_subresources(self, session: AsyncSession, html: str):
        try:
            soup = BeautifulSoup(html, "html.parser")
            if self.follow_pagination:
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if ("?page=" in href or "comments," in href) and not href.endswith("page=0") and not href.endswith("comments,0.html"):
                        page_url = urljoin("https://zapytaj.onet.pl", href)
                        r = await self._safe_fetch(session, page_url, allow_redirects=True)
                        if r and r.status_code == 200:
                            self.warc_manager.write_response(page_url, 200, "OK", dict(r.headers), r.content)
                        await asyncio.sleep(self.delay_per_worker)

            if self.download_images:
                seen_imgs = set()
                for img in soup.find_all("img"):
                    src = img.get("src") or img.get("data-src") or img.get("data-original")
                    if src and ("ocdn.eu/zapytaj" in src or "images.zapytaj.com.pl" in src) and "loading.gif" not in src:
                        img_url = urljoin("https://zapytaj.onet.pl", src)
                        if img_url in seen_imgs:
                            continue
                        seen_imgs.add(img_url)
                        r = await self._safe_fetch(session, img_url, allow_redirects=True)
                        if r and r.status_code == 200:
                            self.warc_manager.write_response(img_url, 200, "OK", dict(r.headers), r.content)
                        await asyncio.sleep(self.delay_per_worker)
        except Exception:
            pass

    async def crawl_range(self, start_id: int, end_id: int):
        self.is_running = True
        step = -1 if start_id >= end_id else 1
        qids = list(range(start_id, end_id + step, step))
        total = len(qids)

        queue = asyncio.Queue()
        for qid in qids:
            queue.put_nowait(qid)

        hb_task = asyncio.create_task(self._heartbeat_worker())
        t_start = time.time()
        print(f"[Crawler] Rozpoczynanie pobierania {total} ID od {start_id} do {end_id} (współbieżność: {self.concurrency})...")

        async with AsyncSession(impersonate="chrome120") as session:
            workers = [
                asyncio.create_task(self._worker_loop(queue, session, total, t_start))
                for _ in range(self.concurrency)
            ]
            await queue.join()
            await asyncio.gather(*workers)

        self.is_running = False
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass

        total_time = time.time() - t_start
        print(f"[Crawler] Ukończono {start_id}->{end_id} w {total_time:.1f}s. Zapisano: {self.saved_count}, 404: {self.not_found_count}")
        return {
            "saved": self.saved_count,
            "not_found": self.not_found_count,
            "skipped": self.skipped_archivebot_count,
            "errors": self.error_count,
            "total_time": total_time
        }
