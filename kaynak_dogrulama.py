
# ============================================================
# MIHVER - KAYNAK DOGRULAMA MOTORU
# Surum: 2.0
#
# - Kalici kaynak kimligi uretir.
# - HTTP erisimini ve yonlendirmeleri kontrol eder.
# - RSS / Atom adreslerini kesfeder.
# - RSS / Atom XML icerigini dogrular.
# - robots.txt kurallarini kontrol eder.
# - 403, 404 ve ag hatalarini ayri raporlar.
# - Kaynaklari otomatik aktiflestirmez.
# - Il / ilce bilgisini kesinlestirmez.
# - Her calismada sinirli sayida kaynak kontrol eder.
# - Kaldigi siradan devam eder.
# - haberler.json dosyasina dokunmaz.
# ============================================================

import json
import re
import time
import hashlib
import urllib.request
import urllib.error
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser


# ------------------------------------------------------------
# DOSYALAR VE AYARLAR
# ------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

KAYNAK_DOSYASI = BASE_DIR / "kaynaklar.json"
DURUM_DOSYASI = BASE_DIR / "dogrulama_durumu.json"
RAPOR_DOSYASI = BASE_DIR / "kaynak_dogrulama_raporu.json"

USER_AGENT = "MIHVER-Kaynak-Dogrulama/2.0"

TIMEOUT = 15
KONTROL_LIMITI = 40
BEKLEME = 1.0
MAKSIMUM_HTML = 1_000_000
MAKSIMUM_XML = 500_000
MAKSIMUM_ROBOTS = 100_000
MAKSIMUM_BESLEME = 12

# RSS tarayicisinin robots.txt icindeki temsilci adi.
ROBOTS_AGENT = "MIHVER-Kaynak-Dogrulama"


# ------------------------------------------------------------
# GENEL YARDIMCILAR
# ------------------------------------------------------------

def simdi():
    return datetime.now(timezone.utc).isoformat()


def json_oku(dosya, varsayilan):
    if not dosya.exists():
        return varsayilan

    with dosya.open("r", encoding="utf-8") as f:
        return json.load(f)


def json_yaz(dosya, veri):
    gecici = dosya.with_name(dosya.name + ".tmp")

    with gecici.open("w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)

    gecici.replace(dosya)


def alan_adi(url):
    try:
        alan = urllib.parse.urlparse(url).hostname or ""
        alan = alan.lower().strip()

        if alan.startswith("www."):
            alan = alan[4:]

        return alan
    except Exception:
        return ""


def guvenli_url(url):
    if not isinstance(url, str):
        return ""

    url = url.strip()

    if not url:
        return ""

    if url.startswith("//"):
        url = "https:" + url

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urllib.parse.urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return ""

        if not parsed.hostname:
            return ""

        if parsed.username or parsed.password:
            return ""

        return url

    except Exception:
        return ""


def kimlik_uret(kaynak):
    # Kimlik, kaynak URL'sinden uretilir.
    # Ayni URL sonraki calismalarda ayni kimligi alir.
    url = guvenli_url(kaynak.get("url", ""))

    temel = url or str(kaynak.get("ad", "isimsiz"))

    return "mihver-" + hashlib.sha256(
        temel.lower().encode("utf-8")
    ).hexdigest()[:20]


def metin_temizle(deger):
    return re.sub(r"\s+", " ", str(deger or "")).strip()


# ------------------------------------------------------------
# HTTP ISTEGI
# ------------------------------------------------------------

def http_istek(url, limit=MAKSIMUM_HTML):
    istek = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/rss+xml,application/atom+xml,"
                "application/xml,text/xml,*/*"
            )
        }
    )

    try:
        with urllib.request.urlopen(
            istek,
            timeout=TIMEOUT
        ) as cevap:

            veri = cevap.read(limit + 1)

            if len(veri) > limit:
                veri = veri[:limit]

            return {
                "basarili": True,
                "durum_kodu": getattr(cevap, "status", 200),
                "son_url": cevap.geturl(),
                "icerik_tipi": cevap.headers.get("Content-Type", ""),
                "veri": veri,
                "hata": None
            }

    except urllib.error.HTTPError as hata:
        return {
            "basarili": False,
            "durum_kodu": hata.code,
            "son_url": hata.geturl(),
            "icerik_tipi": "",
            "veri": b"",
            "hata": "HTTP " + str(hata.code)
        }

    except Exception as hata:
        return {
            "basarili": False,
            "durum_kodu": None,
            "son_url": url,
            "icerik_tipi": "",
            "veri": b"",
            "hata": str(hata)[:250]
        }


# ------------------------------------------------------------
# HTML RSS / ATOM ADRESI BULUCU
# ------------------------------------------------------------

class BeslemeBulucu(HTMLParser):

    def __init__(self):
        super().__init__()
        self.beslemeler = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "link":
            return

        attrs = dict(attrs)

        rel = attrs.get("rel", "").lower()
        tip = attrs.get("type", "").lower()
        href = attrs.get("href", "")

        if not href or "alternate" not in rel:
            return

        if any(x in tip for x in ("rss", "atom", "xml")):
            self.beslemeler.append(href)


def html_beslemelerini_bul(html, ana_url):
    bulunan = []
    parser = BeslemeBulucu()

    try:
        parser.feed(html)
    except Exception:
        return bulunan

    for href in parser.beslemeler:
        adres = guvenli_url(
            urllib.parse.urljoin(ana_url, href)
        )

        if adres and adres not in bulunan:
            bulunan.append(adres)

    return bulunan


# ------------------------------------------------------------
# OLASI RSS / ATOM YOLLARI
# ------------------------------------------------------------

def olasi_besleme_adresleri(ana_url):
    yollar = [
        "/feed",
        "/feed/",
        "/rss",
        "/rss/",
        "/rss.xml",
        "/feed.xml",
        "/atom.xml",
        "/feeds/posts/default",
        "/?feed=rss2"
    ]

    bulunan = []

    for yol in yollar:
        adres = urllib.parse.urljoin(
            ana_url.rstrip("/") + "/",
            yol.lstrip("/")
        )

        if adres not in bulunan:
            bulunan.append(adres)

    return bulunan


# ------------------------------------------------------------
# RSS / ATOM XML ICERIK DOGRULAMASI
# ------------------------------------------------------------

def xml_besleme_bilgisi(xml_verisi):
    if not xml_verisi:
        return {
            "gecerli": False,
            "tur": None,
            "kayit_sayisi": 0
        }

    try:
        kok = ET.fromstring(xml_verisi)
        etiket = kok.tag.split("}")[-1].lower()

        if etiket == "rss":
            tur = "rss"
        elif etiket == "feed":
            tur = "atom"
        elif etiket == "rdf":
            tur = "rss_rdf"
        else:
            return {
                "gecerli": False,
                "tur": None,
                "kayit_sayisi": 0
            }

        kayit_sayisi = 0

        for eleman in kok.iter():
            alt_etiket = eleman.tag.split("}")[-1].lower()

            if alt_etiket in ("item", "entry"):
                kayit_sayisi += 1

        return {
            "gecerli": kayit_sayisi > 0,
            "tur": tur,
            "kayit_sayisi": kayit_sayisi
        }

    except (ET.ParseError, ValueError):
        return {
            "gecerli": False,
            "tur": None,
            "kayit_sayisi": 0
        }


def besleme_kontrol(adres):
    sonuc = http_istek(adres, limit=MAKSIMUM_XML)

    if not sonuc["basarili"]:
        return {
            "adres": adres,
            "durum": "erisilemedi",
            "http_kodu": sonuc["durum_kodu"],
            "son_url": sonuc["son_url"]
        }

    bilgi = xml_besleme_bilgisi(sonuc["veri"])

    if bilgi["gecerli"]:
        durum = "rss_atom_icerigi_gecerli"
    elif bilgi["tur"]:
        durum = "besleme_bos"
    else:
        durum = "gecerli_besleme_degil"

    return {
        "adres": adres,
        "durum": durum,
        "http_kodu": sonuc["durum_kodu"],
        "son_url": sonuc["son_url"],
        "tur": bilgi["tur"],
        "kayit_sayisi": bilgi["kayit_sayisi"]
    }


# ------------------------------------------------------------
# ROBOTS.TXT KONTROLU
# ------------------------------------------------------------

def robots_kontrol(ana_url):
    parsed = urllib.parse.urlparse(ana_url)

    robots_url = (
        parsed.scheme + "://" + parsed.netloc + "/robots.txt"
    )

    sonuc = http_istek(
        robots_url,
        limit=MAKSIMUM_ROBOTS
    )

    if not sonuc["basarili"]:
        if sonuc["durum_kodu"] == 404:
            durum = "robots_dosyasi_yok"
        elif sonuc["durum_kodu"] == 403:
            durum = "robots_erisim_engelli"
        else:
            durum = "robots_kontrol_edilemedi"

        return {
            "adres": robots_url,
            "durum": durum,
            "izin_durumu": "bilinmiyor",
            "icerik": ""
        }

    metin = sonuc["veri"].decode(
        "utf-8",
        errors="replace"
    )

    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(metin.splitlines())

    return {
        "adres": robots_url,
        "durum": "robots_dosyasi_bulundu",
        "izin_durumu": "kurallar_yuklendi",
        "icerik": metin[:20000],
        "_parser": parser
    }


def robots_izinli(robots, url):
    if not robots:
        return False

    parser = robots.get("_parser")

    if parser is None:
        # Robots okunamadiysa guvenli tarafta kal.
        return False

    try:
        return parser.can_fetch(ROBOTS_AGENT, url)
    except Exception:
        return False


# ------------------------------------------------------------
# BIR KAYNAGIN TAM KONTROLU
# ------------------------------------------------------------

def kaynak_kontrol(kaynak):
    url = guvenli_url(kaynak.get("url", ""))

    rapor = {
        "kontrol_tarihi": simdi(),
        "url": url,
        "eski_alan": alan_adi(url),
        "erisim": "kontrol_edilmedi",
        "http_kodu": None,
        "son_url": None,
        "yonlendirme": None,
        "yeni_alan": None,
        "rss_adresleri": [],
        "rss_testleri": [],
        "rss_durumu": "bulunamadi",
        "robots": None,
        "hata": None
    }

    if not url:
        rapor["erisim"] = "gecersiz_adres"
        rapor["hata"] = "Kaynak URL alani bos veya gecersiz."
        return rapor

    sonuc = http_istek(url)

    rapor["http_kodu"] = sonuc["durum_kodu"]

    if not sonuc["basarili"]:
        kod = sonuc["durum_kodu"]

        if kod == 403:
            rapor["erisim"] = "erisime_engel"
        elif kod == 404:
            rapor["erisim"] = "sayfa_bulunamadi"
        else:
            rapor["erisim"] = "erisilemedi"

        rapor["hata"] = sonuc["hata"]
        return rapor

    son_url = sonuc["son_url"]
    yeni_alan = alan_adi(son_url)

    rapor["erisim"] = "erisilebilir"
    rapor["son_url"] = son_url
    rapor["yeni_alan"] = yeni_alan
    rapor["yonlendirme"] = (
        "var"
        if son_url.rstrip("/") != url.rstrip("/")
        else "yok"
    )

    icerik_tipi = (sonuc["icerik_tipi"] or "").lower()

    html_icerik = (
        "html" in icerik_tipi
        or b"<html" in sonuc["veri"][:1000].lower()
    )

    besleme_adresleri = []

    if html_icerik:
        html = sonuc["veri"].decode(
            "utf-8",
            errors="replace"
        )

        besleme_adresleri.extend(
            html_beslemelerini_bul(html, son_url)
        )

    besleme_adresleri.extend(
        olasi_besleme_adresleri(son_url)
    )

    besleme_adresleri = list(dict.fromkeys(besleme_adresleri))

    # Robots kurallarini RSS isteklerinden once oku.
    robots = robots_kontrol(son_url)

    rapor["robots"] = {
        "adres": robots.get("adres"),
        "durum": robots.get("durum"),
        "izin_durumu": robots.get("izin_durumu")
    }

    for adres in besleme_adresleri[:MAKSIMUM_BESLEME]:
        if not robots_izinli(robots, adres):
            rapor["rss_testleri"].append({
                "adres": adres,
                "durum": "robots_izin_vermedi_veya_belirsiz"
            })
            continue

        test = besleme_kontrol(adres)
        rapor["rss_testleri"].append(test)

        if test["durum"] == "rss_atom_icerigi_gecerli":
            rapor["rss_adresleri"].append(test["son_url"] or adres)

        time.sleep(0.2)

    rapor["rss_adresleri"] = list(
        dict.fromkeys(rapor["rss_adresleri"])
    )

    if rapor["rss_adresleri"]:
        rapor["rss_durumu"] = "icerik_dogrulandi"
    elif any(
        x.get("durum") == "robots_izin_vermedi_veya_belirsiz"
        for x in rapor["rss_testleri"]
    ):
        rapor["rss_durumu"] = "robots_nedeniyle_test_edilemedi"
    elif rapor["rss_testleri"]:
        rapor["rss_durumu"] = "gecerli_besleme_bulunamadi"
    else:
        rapor["rss_durumu"] = "bulunamadi"

    return rapor


# ------------------------------------------------------------
# KAYNAK KAYDINI GUNCELLE
# ------------------------------------------------------------

def kaynak_guncelle(kaynak, rapor):
    kaynak["kimlik"] = kaynak.get("kimlik") or kimlik_uret(kaynak)

    kaynak.setdefault("dogrulama", {})

    kaynak["dogrulama"]["adres"] = rapor["erisim"]
    kaynak["dogrulama"]["rss"] = rapor["rss_durumu"]
    kaynak["dogrulama"]["son_kontrol"] = rapor["kontrol_tarihi"]

    kaynak["son_kontrol"] = rapor["kontrol_tarihi"]
    kaynak["rss_adresleri"] = rapor["rss_adresleri"]

    kaynak["kontrol_raporu"] = {
        "http_kodu": rapor["http_kodu"],
        "erisim": rapor["erisim"],
        "yonlendirme": rapor["yonlendirme"],
        "son_url": rapor["son_url"],
        "eski_alan": rapor["eski_alan"],
        "yeni_alan": rapor["yeni_alan"],
        "rss_adresleri": rapor["rss_adresleri"],
        "rss_testleri": rapor["rss_testleri"],
        "rss_durumu": rapor["rss_durumu"],
        "robots": rapor["robots"],
        "hata": rapor["hata"]
    }

    if (
        rapor.get("yeni_alan")
        and rapor["yeni_alan"] != rapor["eski_alan"]
    ):
        kaynak["alan_dogrulama_uyarisi"] = (
            "Yonlendirme farkli alan adina gidiyor; "
            "manuel inceleme gerekiyor."
        )

    kaynak.setdefault("dogrulama", {})
    kaynak["dogrulama"].setdefault(
        "il",
        "manuel_dogrulama_gerekli"
    )
    kaynak["dogrulama"].setdefault(
        "ilce",
        "manuel_dogrulama_gerekli"
    )

    # Bu motor kaynaklari aktiflestirmez.
    return kaynak


# ------------------------------------------------------------
# KONTROL SIRASI
# ------------------------------------------------------------

def kontrol_sirasi(kaynaklar):
    sirali = []

    for i, kaynak in enumerate(kaynaklar):
        if not isinstance(kaynak, dict):
            continue

        if guvenli_url(kaynak.get("url", "")):
            sirali.append(i)

    return sirali


# ------------------------------------------------------------
# ANA PROGRAM
# ------------------------------------------------------------

def ana():
    print("=" * 60)
    print("MIHVER KAYNAK DOGRULAMA MOTORU 2.0")
    print("=" * 60)

    veri = json_oku(
        KAYNAK_DOSYASI,
        {"iller": [], "kaynaklar": []}
    )

    if not isinstance(veri, dict):
        raise ValueError("kaynaklar.json bicimi gecersiz.")

    if not isinstance(veri.get("kaynaklar"), list):
        raise ValueError("kaynaklar alani liste degil.")

    durum = json_oku(
        DURUM_DOSYASI,
        {"sira": 0}
    )

    if not isinstance(durum, dict):
        durum = {"sira": 0}

    kaynaklar = veri["kaynaklar"]
    sirali = kontrol_sirasi(kaynaklar)

    if not sirali:
        print("Kontrol edilecek URL bulunamadi.")
        return

    try:
        sira = int(durum.get("sira", 0)) % len(sirali)
    except (TypeError, ValueError):
        sira = 0

    kontrol_edilen = 0
    erisilebilir = 0
    erisime_engel = 0
    erisilemeyen = 0
    rss_bulunan = 0

    raporlar = []

    adet = min(KONTROL_LIMITI, len(sirali))

    print("Toplam kaynak:", len(kaynaklar))
    print("URL bulunan kaynak:", len(sirali))
    print("Baslangic sirasi:", sira)

    for adim in range(adet):
        pozisyon = (sira + adim) % len(sirali)
        kaynak_indeksi = sirali[pozisyon]
        kaynak = kaynaklar[kaynak_indeksi]

        print("\nKontrol:", adim + 1, "/", adet)
        print("Kaynak:", kaynak.get("ad", "Isimsiz"))
        print("URL:", kaynak.get("url", ""))

        kimlik = kaynak.get("kimlik") or kimlik_uret(kaynak)

        try:
            sonuc = kaynak_kontrol(kaynak)
            kaynak_guncelle(kaynak, sonuc)

            raporlar.append({
                "kimlik": kimlik,
                "ad": kaynak.get("ad"),
                "il": kaynak.get("il"),
                "ilce": kaynak.get("ilce"),
                "rapor": sonuc
            })

            kontrol_edilen += 1

            if sonuc["erisim"] == "erisilebilir":
                erisilebilir += 1
            elif sonuc["erisim"] == "erisime_engel":
                erisime_engel += 1
            else:
                erisilemeyen += 1

            if sonuc["rss_durumu"] == "icerik_dogrulandi":
                rss_bulunan += 1

        except Exception as hata:
            print("Kontrol hatasi:", str(hata)[:200])

            kaynak.setdefault("kimlik", kimlik)
            kaynak.setdefault("dogrulama", {})
            kaynak["dogrulama"]["adres"] = "kontrol_hatasi"

            raporlar.append({
                "kimlik": kimlik,
                "ad": kaynak.get("ad"),
                "il": kaynak.get("il"),
                "ilce": kaynak.get("ilce"),
                "rapor": {
                    "erisim": "kontrol_hatasi",
                    "hata": str(hata)[:250]
                }
            })

        durum["sira"] = (pozisyon + 1) % len(sirali)
        durum["son_calisma"] = simdi()

        # Her 5 kaynakta bir kaydet.
        if (adim + 1) % 5 == 0:
            json_yaz(KAYNAK_DOSYASI, veri)
            json_yaz(DURUM_DOSYASI, durum)

        time.sleep(BEKLEME)

    # Son kayitlar.
    json_yaz(KAYNAK_DOSYASI, veri)
    json_yaz(DURUM_DOSYASI, durum)

    rapor = {
        "surum": "2.0",
        "tarih": simdi(),
        "toplam_kaynak": len(kaynaklar),
        "url_olan_kaynak": len(sirali),
        "bu_calisma_kontrol_edilen": kontrol_edilen,
        "erisilebilir": erisilebilir,
        "erisime_engel": erisime_engel,
        "erisilemeyen": erisilemeyen,
        "rss_icerigi_dogrulanan": rss_bulunan,
        "sonraki_sira": durum["sira"],
        "sonuclar": raporlar
    }

    json_yaz(RAPOR_DOSYASI, rapor)

    print("\n" + "=" * 60)
    print("KAYNAK KONTROLU TAMAMLANDI")
    print("=" * 60)
    print("Kontrol edilen:", kontrol_edilen)
    print("Erisilebilir:", erisilebilir)
    print("Erisime engel:", erisime_engel)
    print("Erisilemeyen:", erisilemeyen)
    print("RSS icerigi dogrulanan:", rss_bulunan)
    print("Toplam kaynak:", len(kaynaklar))
    print("Sonraki baslangic:", durum["sira"])

    print("\nOlusturulan dosyalar:")
    print("- kaynaklar.json")
    print("- dogrulama_durumu.json")
    print("- kaynak_dogrulama_raporu.json")


if __name__ == "__main__":
    ana()
