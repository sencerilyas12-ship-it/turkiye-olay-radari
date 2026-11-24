
import json
import time
import re
import hashlib
import xml.etree.ElementTree as ET

from pathlib import Path
from urllib.parse import urlparse, urljoin, quote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


ROOT = Path(__file__).resolve().parent

ILCELER_DOSYASI = ROOT / "ilceler.json"
KAYNAKLAR_DOSYASI = ROOT / "kaynaklar_ek.json"

ISTEK_ZAMANI = 15
BEKLEME_SANIYESI = 0.5
MAKSIMUM_YENI_KAYNAK = 100

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
)


def web_istegi(url, timeout=ISTEK_ZAMANI):
    """Bir URL'yi güvenli şekilde indirir."""
    try:
        istek = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, "
                          "application/xml, text/xml, text/html, */*"
            }
        )

        with urlopen(istek, timeout=timeout) as cevap:
            veri = cevap.read(2_000_000)
            return veri, cevap.geturl()

    except (URLError, HTTPError, TimeoutError, OSError, ValueError):
        return None, None


def json_oku(dosya, varsayilan):
    try:
        with open(dosya, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return varsayilan


def json_kaydet(dosya, veri):
    gecici = dosya.with_suffix(dosya.suffix + ".tmp")

    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)

    gecici.replace(dosya)


def illeri_yukle():
    veri = json_oku(ILCELER_DOSYASI, {})
    iller = veri.get("cities", [])

    sonuc = []

    for il in iller:
        ad = str(il.get("name", "")).strip()

        if ad and ad not in sonuc:
            sonuc.append(ad)

    return sonuc


def kaynaklari_yukle():
    veri = json_oku(KAYNAKLAR_DOSYASI, {"kaynaklar": []})

    if isinstance(veri, list):
        veri = {"kaynaklar": veri}

    if not isinstance(veri, dict):
        veri = {"kaynaklar": []}

    if not isinstance(veri.get("kaynaklar"), list):
        veri["kaynaklar"] = []

    return veri


def alan_adi(url):
    try:
        alan = urlparse(url).netloc.lower()
        alan = alan.split("@")[-1].split(":")[0]

        if alan.startswith("www."):
            alan = alan[4:]

        return alan
    except Exception:
        return ""


def google_haberler_rss(il):
    sorgu = quote(f'"yerel haber" OR "son dakika" {il}')
    return (
        "https://news.google.com/rss/search?q="
        + sorgu
        + "&hl=tr&gl=TR&ceid=TR:tr"
    )


def google_kaynaklarini_bul(il):
    """Google Haberler RSS sonuçlarından yayıncı sitelerini çıkarır."""
    url = google_haberler_rss(il)
    veri, _ = web_istegi(url)

    if not veri:
        return []

    try:
        kok = ET.fromstring(veri)
    except ET.ParseError:
        return []

    bulunanlar = []
    gorulen_alanlar = set()

    for oge in kok.findall(".//item"):
        kaynak = oge.find("source")

        if kaynak is None:
            continue

        site_url = kaynak.attrib.get("url", "").strip()
        site_adi = (kaynak.text or "").strip()

        if not site_url or not site_adi:
            continue

        if not site_url.startswith(("http://", "https://")):
            continue

        alan = alan_adi(site_url)

        if not alan or alan in gorulen_alanlar:
            continue

        gorulen_alanlar.add(alan)

        bulunanlar.append({
            "ad": site_adi,
            "site": site_url
        })

    return bulunanlar


def rss_adreslerini_bul(site_url):
    """Sitenin ana sayfasından RSS bağlantılarını ve yaygın adresleri bulur."""
    veri, son_url = web_istegi(site_url)

    if not veri:
        return []

    if not son_url:
        son_url = site_url

    try:
        html = veri.decode("utf-8", errors="ignore")
    except Exception:
        return []

    adaylar = []

    # HTML içindeki RSS ve Atom bağlantıları
    desen = re.compile(
        r'<link\b[^>]*>',
        re.IGNORECASE
    )

    for etiket in desen.findall(html):
        tip = re.search(
            r'type=["\']([^"\']+)["\']',
            etiket,
            re.IGNORECASE
        )
        href = re.search(
            r'href=["\']([^"\']+)["\']',
            etiket,
            re.IGNORECASE
        )

        if not tip or not href:
            continue

        tip_degeri = tip.group(1).lower()

        if "rss" in tip_degeri or "atom" in tip_degeri or "xml" in tip_degeri:
            adaylar.append(urljoin(son_url, href.group(1)))

    # Sık kullanılan RSS adresleri
    yaygin_yollar = [
        "/feed",
        "/feed/",
        "/rss",
        "/rss/",
        "/rss.xml",
        "/feed.xml",
        "/index.xml",
        "/atom.xml",
        "/?feed=rss2"
    ]

    for yol in yaygin_yollar:
        adaylar.append(urljoin(son_url, yol))

    # Tekrarlanan adresleri temizle
    temiz = []
    gorulen = set()

    for adres in adaylar:
        adres = adres.strip()

        if adres and adres not in gorulen:
            gorulen.add(adres)
            temiz.append(adres)

    return temiz


def rss_dogrula(rss_url):
    """Adresin gerçekten okunabilir RSS/Atom XML'i olup olmadığını kontrol eder."""
    veri, son_url = web_istegi(rss_url)

    if not veri:
        return False, None

    try:
        kok = ET.fromstring(veri)
    except ET.ParseError:
        return False, None

    etiket = kok.tag.lower()

    if (
        "rss" in etiket
        or "feed" in etiket
        or "rdf" in etiket
    ):
        return True, son_url or rss_url

    return False, None


def mevcut_adresler(kaynaklar):
    adresler = set()
    alanlar = set()

    for kaynak in kaynaklar:
        if not isinstance(kaynak, dict):
            continue

        rss = (
            kaynak.get("rss")
            or kaynak.get("rss_url")
            or kaynak.get("url")
            or ""
        )

        if rss:
            adresler.add(rss.strip())

        site = kaynak.get("site", "")
        if site:
            alanlar.add(alan_adi(site))

    return adresler, alanlar


def kaynak_kesfi():
    print("MIHVER saatlik kaynak keşfi başladı.")

    iller = illeri_yukle()

    if not iller:
        print("HATA: ilceler.json içinden iller okunamadı.")
        return

    veri = kaynaklari_yukle()
    kaynaklar = veri["kaynaklar"]

    adresler, alanlar = mevcut_adresler(kaynaklar)

    eklenen = 0
    incelenen_site = 0

    for il in iller:
        if eklenen >= MAKSIMUM_YENI_KAYNAK:
            break

        print(f"Kaynak aranıyor: {il}")

        siteler = google_kaynaklarini_bul(il)

        for site in siteler:
            if eklenen >= MAKSIMUM_YENI_KAYNAK:
                break

            site_url = site["site"]
            alan = alan_adi(site_url)

            if not alan or alan in alanlar:
                continue

            incelenen_site += 1

            rss_adaylari = rss_adreslerini_bul(site_url)

            for rss_url in rss_adaylari:
                if rss_url in adresler:
                    continue

                gecerli, dogrulanmis_url = rss_dogrula(rss_url)

                if not gecerli:
                    continue

                if dogrulanmis_url in adresler:
                    continue

                yeni_kaynak = {
                    "ad": site["ad"],
                    "il": il,
                    "ilce": "",
                    "site": site_url,
                    "rss": dogrulanmis_url,
                    "kesif_kaynagi": "Google Haberler",
                    "dogrulama": "RSS doğrulandı"
                }

                kaynaklar.append(yeni_kaynak)

                adresler.add(dogrulanmis_url)
                alanlar.add(alan)

                eklenen += 1

                print(
                    f"YENİ KAYNAK: {site['ad']} | "
                    f"{dogrulanmis_url}"
                )

                break

            time.sleep(BEKLEME_SANIYESI)

        time.sleep(BEKLEME_SANIYESI)

    veri["kaynaklar"] = kaynaklar
    veri["son_kesif"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime()
    )
    veri["son_kesifte_incelenen_site"] = incelenen_site
    veri["son_kesifte_eklenen_kaynak"] = eklenen

    json_kaydet(KAYNAKLAR_DOSYASI, veri)

    print("--------------------------------")
    print("Kaynak keşfi tamamlandı.")
    print(f"Taranan il sayısı: {len(iller)}")
    print(f"İncelenen site: {incelenen_site}")
    print(f"Eklenen yeni RSS kaynağı: {eklenen}")
    print(f"Toplam kayıtlı kaynak: {len(kaynaklar)}")


if __name__ == "__main__":
    kaynak_kesfi()
