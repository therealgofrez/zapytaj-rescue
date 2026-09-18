<!-- Improved compatibility of back to top link: See: https://github.com/othneildrew/Best-README-Template/pull/73 -->
<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
<div align="center">

[![Python Version][python-shield]][python-url]
[![License: MIT][license-shield]][license-url]
[![WARC Standard][warc-shield]][warc-url]
[![Live Dashboard][dashboard-shield]][dashboard-url]
[![Docker][docker-shield]][docker-url]

</div>

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <h1 align="center">Zapytaj Onet Rescue (Community Archiver)</h1>

  <p align="center">
    <strong>Zorganizowana, rozproszona archiwizacja 33,4 miliona pytań i odpowiedzi z serwisu Zapytaj.onet.pl przed jego ostatecznym wyłączeniem 30 września 2026 roku.</strong>
    <br />
    <br />
    <a href="http://norbert232.mikrus.xyz:20232/"><strong>Zobacz Dashboard Koordynatora na Żywo »</strong></a>
    <br />
    <br />
    <a href="#-jak-dołączyć-jako-wolontariusz">Wolontariat</a>
    ·
    <a href="https://archive.org/details/zapytaj_onet_mikrus_srv68_chunk00001_20260914183126">Przykładowy zrzut na IA</a>
    ·
    <a href="http://norbert232.mikrus.xyz:20232/">Status projektu</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details open>
  <summary>Spis treści</summary>
  <ol>
    <li>
      <a href="#-o-projekcie">O projekcie</a>
      <ul>
        <li><a href="#dlaczego-ten-projekt-jest-krytyczny">Dlaczego ten projekt jest krytyczny?</a></li>
        <li><a href="#kluczowe-założenia-techniczne">Kluczowe założenia techniczne</a></li>
        <li><a href="#technologie">Technologie</a></li>
      </ul>
    </li>
    <li>
      <a href="#-jak-dołączyć-jako-wolontariusz">Szybki start</a>
      <ul>
        <li><a href="#krok-1-pobranie-kodu">Krok 1: Pobranie kodu</a></li>
        <li><a href="#krok-2-klucze-internet-archive-w-env">Krok 2: Klucze Internet Archive w .env</a></li>
        <li><a href="#krok-3-uruchomienie">Krok 3: Uruchomienie (Windows / Linux / Docker)</a></li>
      </ul>
    </li>
    <li><a href="#-jak-postawić-własnego-koordynatora-dla-organizatorów">Własny serwer koordynatora</a></li>
    <li><a href="#-roadmapa-i-postępy">Roadmapa i postępy</a></li>
    <li><a href="#-licencja">Licencja</a></li>
  </ol>
</details>

---

<!-- ABOUT THE PROJECT -->
## 📖 O projekcie

Serwis **Zapytaj.onet.pl** (dawniej *Zapytaj.com.pl*, działający od 2006 roku) ogłosił zakończenie działalności:
- **21 września 2026 r.** – przejście w tryb *read-only* (blokada zadawania i odpowiadania na pytania).
- **30 września 2026 r.** – całkowite wyłączenie serwerów i **trwałe usunięcie wszystkich danych**.

W bazie serwisu znajduje się ponad **33 400 000 pytań**, setki milionów odpowiedzi i wiele kont użytkowników.

### Dlaczego ten projekt jest krytyczny?
Oficjalny bot ArchiveTeam (*ArchiveBot*, zadanie `673i9jafj0idyemybm1p7up5h`) działa jako pojedynczy proces. W ciągu pierwszych 10 dni od ogłoszenia zamknięcia pobrał zaledwie **~306 000 pytań** (mniej niż **1%** całości), marnując czas na badanie zewnętrznych linków. W tym tempie ArchiveTeam zabezpieczyłby zaledwie ułamek procenta serwisu.

Ten projekt pozwala **każdemu chętnemu** włączyć się do akcji ratunkowej w modelu rozproszonym (*community warrior*).

### Założenia techniczne:
1. **Zbieranie od końca (Reverse ID Crawl):** Skrypt zaczyna od najwyższego aktywnego identyfikatora (`33 408 830`) i schodzi w dół. Bot ArchiveTeamu idzie standardowo od początku (BFS) dzięki czemu nie dubluje pracy.
2. **Deduplikacja w czasie rzeczywistym:** Skrypt synchronizuje opublikowane indeksy CDX ArchiveBota z Internet Archive i **automatycznie pomija** pytania, które bot już zabezpieczył (baza ponad 306k znanych ID).
3. **Automatyczny podział paczek:** Centralny koordynator dzieli bazę na równe paczki (po 25 000 ID)..
4. **Standard WARC ISO 28500:** Każda pobrana strona jest zapisywana do formatu `.warc.gz` z zachowaniem nagłówków HTTP, kolejnych stron odpowiedzi (`?page=...`) oraz zdjęć z CDN (`ocdn.eu`). format akceptowany natywnie przez **Wayback Machine**.
5. **Automatyczne wysyłanie:** Po ukończeniu każdej paczki (25k pytań) plik WARC natychmiast jest publikowany do Internet Archive, weryfikuje sumę SHA-256 i usuwa lokalną kopię

<p align="right">(<a href="#readme-top">do góry</a>)</p>

---

### Technologie

* [![Python][Python.org]][Python-url]
* [![FastAPI][FastAPI.tiangolo.com]][FastAPI-url]
* [![Docker][Docker.com]][Docker-url]
* [![SQLite][SQLite.org]][SQLite-url]
* **`curl_cffi`** – obsługa TLS fingerprinting (omijanie CloudFront WAF)
* **`warcio`** – strumieniowy zapis w standardzie Web ARChive (ISO 28500)
* **`internetarchive`** – oficjalne API do bezpośredniego uploadu zbiorów na Archive.org

<p align="right">(<a href="#readme-top">do góry</a>)</p>

---

<!-- GETTING STARTED -->
## 👥 Jak dołączyć jako wolontariusz?

Wystarczy dowolny komputer z dostępem do internetu (Windows, Linux, macOS lub VPS).

### Krok 1: Pobranie kodu
Sklonuj repozytorium lub pobierz je jako ZIP (zielony przycisk **Code -> Download ZIP**):
```bash
git clone https://github.com/therealgofrez/zapytaj-rescue.git
cd zapytaj-rescue
```

---

### Krok 2: Klucze Internet Archive w `.env`
Aby pobrane pytania od razu trafiały do Wayback Machine:

1. Zaloguj się na darmowe konto na **[archive.org](https://archive.org/)**.
2. Otwórz stronę generatora kluczy: **[archive.org/account/s3.php](https://archive.org/account/s3.php)** i kliknij *Generate New Keys*.
3. Skopiuj plik `.env.example` jako `.env`:
   ```bash
   cp .env.example .env
   ```

4. Wpisz swój nick oraz wygenerowane klucze:
   ```env
   VOLUNTEER_NAME=twoj_nick
   COORDINATOR_URL=http://norbert232.mikrus.xyz:20232
   AUTO_UPLOAD=true
   IA_ACCESS_KEY=twoj_access_key
   IA_SECRET_KEY=twoj_secret_key
   ```


---

### Krok 3: Uruchomienie

Wybierz najwygodniejszą dla siebie metodę:

#### A) Windows:
Kliknij dwukrotnie plik **`start.bat`**.

#### B) Linux / macOS:
```bash
chmod +x start.sh
./start.sh
```

#### C) Docker:
```bash
docker compose up -d worker
```

#### D) Python:
```bash
python -m pip install -r requirements.txt
python main.py worker
```

Twój worker od razu pojawi się na żywo w panelu koordynatora:  
👉 **[http://norbert232.mikrus.xyz:20232/](http://norbert232.mikrus.xyz:20232/)**

<p align="right">(<a href="#readme-top">do góry</a>)</p>

---

<!-- COORDINATOR SETUP -->
## 🖥️ Jak postawić własnego Koordynatora

Domyślnie wszyscy łączą się z działającym koordynatorem pod adresem `http://norbert232.mikrus.xyz:20232`. Jeśli chcesz postawić własny serwer zarządzający:

1. Uruchom serwer koordynatora:
   ```bash
   python main.py server --host 0.0.0.0 --port 8000
   ```
2. Koordynator utworzy bazę SQLite `coordinator.db` z paczkami i uruchomi panel pod `http://localhost:8000/`.

<p align="right">(<a href="#readme-top">do góry</a>)</p>

---

<!-- ROADMAP -->
## 🗺️ Roadmapa i postępy

- [x] Odkrycie i przetestowanie struktury URL pytań Zapytaj Onet
- [x] Implementacja silnika asynchronicznego opartego o `curl_cffi` z omijaniem bot-protection
- [x] Implementacja modułu deduplikacji z jobem ArchiveBota (`dedup.py`)
- [x] Zapis danych w standardzie WARC (ISO 28500) z nagłówkami `warcinfo`
- [x] Stworzenie serwera koordynatora z bazą chunków, heartbeatem i web dashboardem
- [x] Wdrożenie produkcyjne serwera koordynatora 24/7 na VPS (`norbert232.mikrus.xyz:20232`)
- [x] Automatyczna wysyłka WARC bezpośrednio na Internet Archive (`mediatype:web`) ze zwolnieniem miejsca na dysku
- [ ] Zabezpieczenie 100% bazy (33.4M pytań) do 30 września 2026 r.

<p align="right">(<a href="#readme-top">do góry</a>)</p>

---

<!-- LICENSE -->
## 📄 Licencja

Projekt udostępniony na licencji MIT. Zobacz plik `LICENSE` po szczegóły.  
Wszelkie zarchiwizowane materiały należą do ich pierwotnych autorów i są zabezpieczane w celach ochrony dziedzictwa cyfrowego w domenie publicznej Internet Archive.

---

<!-- MARKDOWN LINKS & IMAGES -->
[python-shield]: https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg?style=for-the-badge&logo=python
[python-url]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge
[license-url]: LICENSE
[warc-shield]: https://img.shields.io/badge/Format-WARC%20ISO%2028500-orange.svg?style=for-the-badge
[warc-url]: https://iipc.github.io/warc-specifications/
[dashboard-shield]: https://img.shields.io/badge/Live_Dashboard-Online-success.svg?style=for-the-badge
[dashboard-url]: http://norbert232.mikrus.xyz:20232/
[docker-shield]: https://img.shields.io/badge/Docker-Ready-2496ED.svg?style=for-the-badge&logo=docker
[docker-url]: Dockerfile
[Python.org]: https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white
[Python-url]: https://www.python.org/
[FastAPI.tiangolo.com]: https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white
[FastAPI-url]: https://fastapi.tiangolo.com/
[Docker.com]: https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white
[Docker-url]: https://www.docker.com/
[SQLite.org]: https://img.shields.io/badge/SQLite-07405E?style=for-the-badge&logo=sqlite&logoColor=white
[SQLite-url]: https://www.sqlite.org/
