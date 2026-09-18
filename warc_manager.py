import os
import time
import io
import threading
from typing import Dict, List, Tuple, Optional
from warcio.warcwriter import WARCWriter
from warcio.statusandheaders import StatusAndHeaders

class WarcManager:
    def __init__(self, output_dir: str = "./warcs", volunteer_name: str = "anonymous", chunk_id: Optional[int] = None):
        self.output_dir = output_dir
        self.volunteer_name = volunteer_name
        self.chunk_id = chunk_id
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.lock = threading.Lock()
        self.current_file = None
        self.writer = None
        self.current_filepath = None
        self.record_count = 0
        self.bytes_written = 0
        
        self._start_new_warc()

    def _get_new_filename(self) -> str:
        timestamp = time.strftime("%Y%m%d%H%M%S")
        chunk_tag = f"chunk{self.chunk_id:05d}_" if self.chunk_id is not None else ""
        return f"zapytaj_onet_{self.volunteer_name}_{chunk_tag}{timestamp}.warc.gz"

    def _start_new_warc(self):
        filename = self._get_new_filename()
        self.current_filepath = os.path.join(self.output_dir, filename)
        self.current_file = open(self.current_filepath, "wb")
        self.writer = WARCWriter(self.current_file, gzip=True)
        self.record_count = 0
        warcinfo_dict = {
            "software": "zapytaj-rescue-archiver/1.0",
            "format": "WARC File Format 1.0",
            "operator": self.volunteer_name,
            "conformsTo": "http://bibnum.bnf.fr/WARC/WARC_Format_Specification_ISO_28500_version_1.0.pdf",
            "description": "Community preservation of Zapytaj Onet (zapytaj.onet.pl)",
            "robots": "ignore",
            "http-header-user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        record = self.writer.create_warcinfo_record(filename, warcinfo_dict)
        self.writer.write_record(record)

    def write_response(self, url: str, status_code: int, reason: str, headers: Dict[str, str], body: bytes):
        """Zapisuje odpowiedź HTTP jako rekord response w formacie WARC."""
        with self.lock:
            if not self.writer:
                self._start_new_warc()

            header_tuples = []
            has_content_length = False
            for k, v in headers.items():
                kl = k.lower()
                if kl.startswith(":") or kl in ("content-encoding", "transfer-encoding", "connection", "keep-alive"):
                    continue
                if kl == "content-length":
                    header_tuples.append((k, str(len(body))))
                    has_content_length = True
                else:
                    header_tuples.append((k, v))

            if not has_content_length:
                header_tuples.append(("Content-Length", str(len(body))))

            http_headers = StatusAndHeaders(f"{status_code} {reason}", header_tuples, protocol="HTTP/1.1")
            payload = io.BytesIO(body)
            
            record = self.writer.create_warc_record(
                url,
                "response",
                payload=payload,
                http_headers=http_headers
            )
            self.writer.write_record(record)
            self.record_count += 1
            self.bytes_written += len(body)

    def close(self) -> Tuple[str, int, int]:
        """Zamyka plik WARC i zwraca (ścieżka_do_pliku, liczba_rekordów, rozmiar_w_bajtach)."""
        with self.lock:
            if self.current_file:
                self.current_file.flush()
                self.current_file.close()
                self.current_file = None
                self.writer = None
            
            size = os.path.getsize(self.current_filepath) if self.current_filepath and os.path.exists(self.current_filepath) else 0
            return self.current_filepath, self.record_count, size
