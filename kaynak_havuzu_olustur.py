
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MİHVER - İlçe Bazlı Kaynak Keşif Motoru
Sürüm 3.1.0

PDF okuma: pypdf
Kaynak keşfi: Google News RSS
Her çalıştırmada: 60 ilçe
Mevcut haberler.json dosyasına dokunmaz.
"""

import json
import re
import hashlib
import urllib.request
import urllib.parse
import os
import time
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timezone
from html import unescape

BASE = Path(__file__).resolve().parent

SOURCES_FILE = BASE / "kaynaklar.json"
STATE_FILE = BASE / "kaynak_havuzu_ilerleme.json"
REPORT_FILE = BASE / "kaynak_havuzu_raporu.json"

USER_AGENT = "Mozilla/5.0 (compatible; MIHVER/3.1)"
BATCH_SIZE = 60
TIMEOUT = 25
PAUSE = 1


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    os.replace(temporary, path)


def fetch(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=TIMEOUT
    ) as response:
        return response.read()


def normalize(value):
    value = unescape(str(value or ""))
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def make_id(url):
    digest = hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()[:20]

    return "mihver-" + digest


def clean_url(url):
    url = normalize(url)

    if not url.startswith(("http://", "https://")):
        return ""

    parsed = urllib.parse.urlsplit(url)

    if not parsed.hostname:
        return ""

    host = parsed.hostname.lower()

    blocked = (
        "google.com",
        "googleusercontent.com",
        "gstatic.com"
    )

    if any(host == item or host.endswith("." + item)
           for item in blocked):
        return ""

    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        "",
        ""
    ))


def get_source_list(data):
    if isinstance(data, list):
        return data, None

    if isinstance(data, dict):
        for key in ("kaynaklar", "sources", "items"):
            if isinstance(data.get(key), list):
                return data[key], key

    raise RuntimeError(
        "kaynaklar.json biçimi tanınmadı. Dosya değiştirilmedi."
    )


def extract_pdf_text(pdf_path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError(
            "pypdf kurulu değil. Workflow içine "
            "'pip install pypdf' adımı eklenmeli."
        )

    reader = PdfReader(pdf_path)
    pages = []

    for page in reader.pages:
        pages.append(page.extract_text() or "")

    text = "\n".join(pages)

    if not text.strip():
        raise RuntimeError(
            "PDF içinden metin çıkarılamadı."
        )

    return text


def download_pdf():
    url = (
        "https://www.alomaliye.com/wp-content/uploads/"
        "2020/05/ilce-listesi.pdf"
    )

    data = fetch(url)

    if not data.startswith(b"%PDF"):
        raise RuntimeError(
            "İlçe listesi PDF olarak alınamadı."
        )

    return data


def parse_districts(text):
    """
    PDF metninden il ve ilçe isimlerini çıkarır.
    922 kayıt doğrulanmadan devam etmez.
    """

    provinces = [
        "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı",
        "Amasya", "Ankara", "Antalya", "Artvin", "Aydın",
        "Balıkesir", "Bilecik", "Bingöl", "Bitlis", "Bolu",
        "Burdur", "Bursa", "Çanakkale", "Çankırı", "Çorum",
        "Denizli", "Diyarbakır", "Edirne", "Elazığ",
        "Erzincan", "Erzurum", "Eskişehir", "Gaziantep",
        "Giresun", "Gümüşhane", "Hakkari", "Hatay",
        "Isparta", "Mersin", "İstanbul", "İzmir", "Kars",
        "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir",
        "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa",
        "Kahramanmaraş", "Mardin", "Muğla", "Muş",
        "Nevşehir", "Niğde", "Ordu", "Rize", "Sakarya",
        "Samsun", "Siirt", "Sinop", "Sivas", "Tekirdağ",
        "Tokat", "Trabzon", "Tunceli", "Şanlıurfa", "Uşak",
        "Van", "Yozgat", "Zonguldak", "Aksaray", "Bayburt",
        "Karaman", "Kırıkkale", "Batman", "Şırnak",
        "Bartın", "Ardahan", "Iğdır", "Yalova", "Karabük",
        "Kilis", "Osmaniye", "Düzce"
    ]

    def key(value):
        value = normalize(value).casefold()
        value = value.replace("i̇", "i")
        return value

    province_lookup = {
        key(province): province
        for province in provinces
    }

    current_province = None
    districts = []
    seen = set()

    for raw in text.splitlines():
        line = normalize(raw)

        if not line:
            continue

        # Aynı satırda il ve ilçe bilgisi bulunabilen PDF tabloları
        parts = re.split(r"\s{2,}|\t+", raw.strip())
        parts = [normalize(part) for part in parts if normalize(part)]

        matched_province = None

        for part in parts:
            candidate = key(part.strip(" :-"))
            if candidate in province_lookup:
                matched_province = province_lookup[candidate]
                break

        if matched_province:
            current_province = matched_province

            for part in parts:
                if key(part) == key(matched_province):
                    continue

                name = normalize(part.strip(" :-"))

                if len(name) < 2:
                    continue

                if re.search(r"\d", name):
                    continue

                pair = (current_province, key(name))

                if pair not in seen:
                    seen.add(pair)
                    districts.append({
                        "il": current_province,
                        "ilce": name.title()
                    })

            continue

        # PDF tek sütunluysa il başlığına göre takip et
        candidate = key(line.strip(" :-"))

        if candidate in province_lookup:
            current_province = province_lookup[candidate]
            continue

        if current_province is None:
            continue

        if re.search(r"\d", line):
            continue

        if len(line) < 2 or len(line) > 45:
            continue

        ignored = (
            "toplam",
            "ilçe sayısı",
            "ilceler",
            "ilçeler",
            "türkiye cumhuriyeti",
            "içişleri bakanlığı"
        )

        if any(word in key(line) for word in ignored):
            continue

        pair = (current_province, key(line))

        if pair not in seen:
            seen.add(pair)
            districts.append({
                "il": current_province,
                "ilce": line.title()
            })

    # Yanlış veya eksik PDF ayrıştırmasıyla veri yazılmasını önle.
    if len(districts) != 922:
        raise RuntimeError(
            f"PDF ayrıştırma sonucu {len(districts)} ilçe. "
            "Beklenen 922. Kaynak dosyası değiştirilmedi."
        )

    return districts


def get_districts():
    pdf_data = download_pdf()

    import tempfile

    with tempfile.NamedTemporaryFile(
        suffix=".pdf",
        delete=False
    ) as file:
        file.write(pdf_data)
        pdf_path = file.name

    try:
        text = extract_pdf_text(pdf_path)
        return parse_districts(text)
    finally:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass


def rss_url(province, district):
    query = f'"{district}" "{province}" yerel haber'

    params = urllib.parse.urlencode({
        "q": query,
        "hl": "tr",
        "gl": "TR",
        "ceid": "TR:tr"
    })

    return (
        "https://news.google.com/rss/search?"
        + params
    )


def parse_rss(data, province, district):
    results = []

    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return results

    for item in root.findall(".//item"):
        source = item.find("source")

        if source is None:
            continue

        url = clean_url(
            source.attrib.get("url", "")
        )

        if not url:
            continue

        name = normalize(source.text)

        results.append({
            "id": make_id(url),
            "ad": name or url,
            "url": url,
            "il": province,
            "ilce": district,
            "kategori": "yerel_basın",
            "durum": "aday",
            "dogrulandi": False,
            "kaynak_turu": "google_news_rss_kesfi",
            "kesif_tarihi": now()
        })

    return results


def main():
    print("MİHVER 3.1 kaynak keşfi başladı.")

    # İlçe listesi doğrulanmadan kaynak dosyasına dokunma.
    districts = get_districts()

    print(f"Doğrulanan ilçe kayıt sayısı: {len(districts)}")

    state = read_json(
        STATE_FILE,
        {"next_index": 0}
    )

    start = int(state.get("next_index", 0))
    start = max(0, min(start, len(districts)))

    end = min(start + BATCH_SIZE, len(districts))

    original_data = read_json(SOURCES_FILE, [])
    sources, source_key = get_source_list(original_data)

    known_urls = set()

    for source in sources:
        if isinstance(source, dict):
            url = clean_url(
                source.get("url")
                or source.get("adres")
                or source.get("link")
                or ""
            )

            if url:
                known_urls.add(url)

    discovered = []
    errors = 0
    checked = 0

    for item in districts[start:end]:
        province = item["il"]
        district = item["ilce"]

        print(f"Tarama: {province} / {district}")

        try:
            data = fetch(rss_url(province, district))

            candidates = parse_rss(
                data,
                province,
                district
            )

            for candidate in candidates:
                url = candidate["url"]

                if url in known_urls:
                    continue

                known_urls.add(url)
                discovered.append(candidate)

        except Exception as error:
            errors += 1
            print(
                f"Kaynak arama hatası: {province}/{district}: {error}"
            )

        checked += 1
        time.sleep(PAUSE)

    updated = sources + discovered

    if isinstance(original_data, list):
        new_data = updated
    else:
        new_data = dict(original_data)
        new_data[source_key] = updated

    # Önce yeni kaynak verisini kaydet.
    save_json(SOURCES_FILE, new_data)

    next_index = end
    completed = next_index >= len(districts)

    if completed:
        next_index = 0

    save_json(STATE_FILE, {
        "surum": "3.1.0",
        "toplam_ilce": len(districts),
        "son_taranan_aralik": [start, end],
        "next_index": next_index,
        "tamamlandi": completed,
        "son_calistirma": now()
    })

    report = {
        "proje": "MİHVER",
        "surum": "3.1.0",
        "tarih": now(),
        "toplam_il": 81,
        "toplam_ilce": len(districts),
        "bu_calismada_taranan_ilce": checked,
        "arama_hatasi": errors,
        "yeni_kaynak_adayi": len(discovered),
        "toplam_kaynak_kaydi": len(updated),
        "tarama_tamamlandi": completed,
        "sonraki_baslangic_sirasi": next_index,
        "not": (
            "Kaynak adayları otomatik keşfedilmiştir. "
            "Yayıncı kimliği ve ilçe aidiyeti ayrıca "
            "doğrulanmalıdır."
        )
    }

    save_json(REPORT_FILE, report)

    print("--------------------------------")
    print("MİHVER kaynak keşfi tamamlandı.")
    print(f"İlçe sayısı: {len(districts)}")
    print(f"Taranan ilçe: {checked}")
    print(f"Yeni kaynak adayı: {len(discovered)}")
    print(f"Toplam kaynak: {len(updated)}")
    print(f"Tarama tamamlandı: {completed}")
    print("--------------------------------")


if __name__ == "__main__":
    main()
