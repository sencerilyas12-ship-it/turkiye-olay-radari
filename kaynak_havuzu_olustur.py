
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MIHVER - İlçe Bazlı Gerçek Kaynak Keşif Motoru
Sürüm: 3.0.0

- 922 ilçelik listeyi İçişleri Bakanlığı PDF listesinden alır.
- Google News RSS üzerinden gerçek yayıncı URL'lerini keşfeder.
- Her çalıştırmada 60 ilçe tarar ve kaldığı yerden devam eder.
- Mevcut kaynakları korur, URL mükerrerlerini eklemez.
- Haberler.json dosyasına dokunmaz.
"""

import json
import re
import hashlib
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import tempfile
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

DISTRICT_PDF = (
    "https://www.alomaliye.com/wp-content/uploads/2020/05/"
    "ilce-listesi.pdf"
)

USER_AGENT = "Mozilla/5.0 (compatible; MIHVER/3.0)"
BATCH_SIZE = 60
REQUEST_TIMEOUT = 25
PAUSE_SECONDS = 1.0


def now():
    return datetime.now(timezone.utc).isoformat()


def fetch(url, timeout=REQUEST_TIMEOUT):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*"
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def load_json(path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_save(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(temp, path)


def get_source_list(data):
    if isinstance(data, list):
        return data, None

    if isinstance(data, dict):
        for key in ("kaynaklar", "sources", "items"):
            if isinstance(data.get(key), list):
                return data[key], key

    raise RuntimeError(
        "kaynaklar.json biçimi tanınamadı. Dosya değiştirilmedi."
    )


def normalize(text):
    text = unescape(str(text or ""))
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def slug_id(url):
    return "mihver-" + hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()[:20]


def clean_url(url):
    url = normalize(url)

    if not url.startswith(("http://", "https://")):
        return ""

    parsed = urllib.parse.urlsplit(url)

    if not parsed.hostname:
        return ""

    if parsed.hostname.endswith("google.com"):
        return ""

    if parsed.hostname.endswith("googleusercontent.com"):
        return ""

    if parsed.hostname.endswith("gstatic.com"):
        return ""

    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        "",
        ""
    ))


def download_district_pdf():
    print("Resmî ilçe listesi indiriliyor...")

    data = fetch(DISTRICT_PDF)

    if not data.startswith(b"%PDF"):
        raise RuntimeError("İlçe listesi PDF olarak alınamadı.")

    with tempfile.NamedTemporaryFile(
        suffix=".pdf", delete=False
    ) as f:
        f.write(data)
        return f.name


def extract_pdf_text(pdf_path):
    result = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60
    )

    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            "PDF metni çıkarılamadı. pdftotext işlemi başarısız."
        )

    return result.stdout


def parse_districts(text):
    """
    İçişleri Bakanlığı ilçe listesi PDF metnini okur.
    İl başlıklarını ve altındaki ilçe isimlerini ayıklar.
    """

    provinces = [
        "ADANA", "ADIYAMAN", "AFYONKARAHİSAR", "AĞRI",
        "AMASYA", "ANKARA", "ANTALYA", "ARTVİN", "AYDIN",
        "BALIKESİR", "BİLECİK", "BİNGÖL", "BİTLİS", "BOLU",
        "BURDUR", "BURSA", "ÇANAKKALE", "ÇANKIRI", "ÇORUM",
        "DENİZLİ", "DİYARBAKIR", "EDİRNE", "ELAZIĞ",
        "ERZİNCAN", "ERZURUM", "ESKİŞEHİR", "GAZİANTEP",
        "GİRESUN", "GÜMÜŞHANE", "HAKKARİ", "HATAY",
        "ISPARTA", "MERSİN", "İSTANBUL", "İZMİR", "KARS",
        "KASTAMONU", "KAYSERİ", "KIRKLARELİ", "KIRŞEHİR",
        "KOCAELİ", "KONYA", "KÜTAHYA", "MALATYA", "MANİSA",
        "KAHRAMANMARAŞ", "MARDİN", "MUĞLA", "MUŞ",
        "NEVŞEHİR", "NİĞDE", "ORDU", "RİZE", "SAKARYA",
        "SAMSUN", "SİİRT", "SİNOP", "SİVAS", "TEKİRDAĞ",
        "TOKAT", "TRABZON", "TUNCELİ", "ŞANLIURFA", "UŞAK",
        "VAN", "YOZGAT", "ZONGULDAK", "AKSARAY", "BAYBURT",
        "KARAMAN", "KIRIKKALE", "BATMAN", "ŞIRNAK",
        "BARTIN", "ARDAHAN", "IĞDIR", "YALOVA", "KARABÜK",
        "KİLİS", "OSMANİYE", "DÜZCE"
    ]

    province_map = {
        p.casefold(): p.title() for p in provinces
    }

    current_province = None
    districts = []
    seen = set()

    for raw_line in text.splitlines():
        line = normalize(raw_line).upper()

        if not line:
            continue

        line = re.sub(
            r"İLÇE SAYISI\s*:\s*\d+",
            "",
            line
        ).strip()

        if not line:
            continue

        # İl başlıkları
        candidate = re.sub(r"[^A-ZÇĞİÖŞÜ]", "", line)

        if candidate.casefold() in province_map:
            current_province = province_map[candidate.casefold()]
            continue

        if current_province is None:
            continue

        if "TOPLAM İLÇE SAYISI" in line:
            continue

        if "İLLER İDARESİ" in line or "İÇİŞLERİ" in line:
            continue

        # PDF satırında yalnızca ilçe adı kalacak şekilde temizle
        name = re.sub(r"[^A-ZÇĞİÖŞÜ]", "", line)

        if len(name) < 2:
            continue

        if name in {
            "İLÇELERGENELLİSTESİ",
            "TÜRKİYECUMHURİYETİ"
        }:
            continue

        key = (current_province, name)

        if key not in seen:
            seen.add(key)
            districts.append({
                "il": current_province,
                "ilce": name.title()
            })

    if len(districts) < 850:
        raise RuntimeError(
            f"PDF'den yalnızca {len(districts)} ilçe çıkarıldı. "
            "Eksik liste kullanılmayacak."
        )

    if len(districts) != 922:
        raise RuntimeError(
            f"PDF'den {len(districts)} kayıt çıkarıldı; "
            "beklenen 922. Liste kontrol edilmeden kullanılmayacak."
        )

    return districts


def get_districts():
    pdf_path = download_district_pdf()

    try:
        text = extract_pdf_text(pdf_path)
        districts = parse_districts(text)
    finally:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass

    return districts


def google_news_rss(province, district):
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


def parse_rss_sources(xml_data, province, district):
    found = []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        return found

    for item in root.findall(".//item"):
        source = item.find("source")

        if source is None:
            continue

        publisher_url = clean_url(
            source.attrib.get("url", "")
        )

        publisher_name = normalize(source.text)

        if not publisher_url:
            continue

        found.append({
            "ad": publisher_name or publisher_url,
            "url": publisher_url,
            "il": province,
            "ilce": district,
            "kategori": "yerel_basın",
            "durum": "aday",
            "dogrulandi": False,
            "kaynak_turu": "google_news_rss_kesfi",
            "kesif_tarihi": now()
        })

    return found


def main():
    print("MİHVER kaynak keşif motoru başlatıldı.")

    # İlçe listesi doğrulanmadan kaynak dosyasına dokunulmaz.
    districts = get_districts()

    print(f"İlçe listesi doğrulandı: {len(districts)}")

    state = load_json(STATE_FILE, {"next_index": 0})

    start = int(state.get("next_index", 0))
    start = max(0, min(start, len(districts)))

    end = min(start + BATCH_SIZE, len(districts))

    print(f"Bu çalıştırmada taranacak ilçe: {start + 1}-{end}")

    original_data = load_json(SOURCES_FILE, [])
    sources, source_key = get_source_list(original_data)

    known_urls = {
        clean_url(
            item.get("url")
            or item.get("adres")
            or item.get("link")
            or ""
        )
        for item in sources
        if isinstance(item, dict)
    }

    known_urls.discard("")

    discovered = []
    checked_districts = 0
    errors = 0

    for district_info in districts[start:end]:
        province = district_info["il"]
        district = district_info["ilce"]

        print(f"Taranıyor: {province} / {district}")

        try:
            rss_url = google_news_rss(province, district)
            rss_data = fetch(rss_url)

            results = parse_rss_sources(
                rss_data,
                province,
                district
            )

            for item in results:
                url = item["url"]

                if url in known_urls:
                    continue

                item["id"] = slug_id(url)
                item["eklenme_tarihi"] = now()

                discovered.append(item)
                known_urls.add(url)

        except Exception as exc:
            errors += 1
            print(
                f"Uyarı: {province}/{district}: {exc}"
            )

        checked_districts += 1
        time.sleep(PAUSE_SECONDS)

    # Sadece yeni ve gerçek yayıncı URL'leri eklenir.
    updated_sources = sources + discovered

    if isinstance(original_data, list):
        updated_data = updated_sources
    else:
        updated_data = dict(original_data)
        updated_data[source_key] = updated_sources

    # Kaynak dosyasını atomik biçimde kaydet.
    atomic_save(SOURCES_FILE, updated_data)

    next_index = end
    completed = next_index >= len(districts)

    if completed:
        next_index = 0

    atomic_save(STATE_FILE, {
        "surum": "3.0.0",
        "next_index": next_index,
        "son_taranan_aralik": [start, end],
        "toplam_ilce": len(districts),
        "tamamlandi": completed,
        "son_calistirma": now()
    })

    report = {
        "proje": "MİHVER",
        "surum": "3.0.0",
        "tarih": now(),
        "toplam_il": 81,
        "toplam_ilce": len(districts),
        "bu_calismada_taranan_ilce": checked_districts,
        "kesif_hatasi": errors,
        "yeni_kaynak_adayi": len(discovered),
        "toplam_kaynak_kaydi": len(updated_sources),
        "tarama_tamamlandi": completed,
        "sonraki_baslangic_sirasi": next_index,
        "not": (
            "Keşfedilen yayıncı adresleri adaydır. "
            "İlçe aidiyeti ve yayıncı kimliği ayrıca "
            "doğrulanmalıdır."
        )
    }

    atomic_save(REPORT_FILE, report)

    print("--------------------------------")
    print("MİHVER kaynak keşfi tamamlandı.")
    print(f"Kontrol edilen ilçe: {checked_districts}")
    print(f"Yeni kaynak adayı: {len(discovered)}")
    print(f"Toplam kaynak kaydı: {len(updated_sources)}")
    print(f"Tarama tamamlandı mı: {completed}")
    print("--------------------------------")


if __name__ == "__main__":
    main()
