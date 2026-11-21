
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MİHVER - Otomatik Kaynak Havuzu Oluşturucu
81 il ve 922 ilçe için kaynak adaylarını oluşturur.
Mevcut kaynakları ve haberleri silmez.
"""

import json
import re
import hashlib
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent
SOURCES_FILE = BASE_DIR / "kaynaklar.json"
REPORT_FILE = BASE_DIR / "kaynak_havuzu_raporu.json"

USER_AGENT = "MIHVER-KaynakEnvanteri/1.0"

# Türkiye'nin 81 ili ve plaka kodları
ILLER = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Amasya",
    "Ankara", "Antalya", "Artvin", "Aydın", "Balıkesir",
    "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur",
    "Bursa", "Çanakkale", "Çankırı", "Çorum", "Denizli",
    "Diyarbakır", "Edirne", "Elazığ", "Erzincan", "Erzurum",
    "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari",
    "Hatay", "Isparta", "Mersin", "İstanbul", "İzmir",
    "Kars", "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir",
    "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa",
    "Kahramanmaraş", "Mardin", "Muğla", "Muş", "Nevşehir",
    "Niğde", "Ordu", "Rize", "Sakarya", "Samsun",
    "Siirt", "Sinop", "Sivas", "Tekirdağ", "Tokat",
    "Trabzon", "Tunceli", "Şanlıurfa", "Uşak", "Van",
    "Yozgat", "Zonguldak", "Aksaray", "Bayburt", "Karaman",
    "Kırıkkale", "Batman", "Şırnak", "Bartın", "Ardahan",
    "Iğdır", "Yalova", "Karabük", "Kilis", "Osmaniye",
    "Düzce"
]

# Kaynak adayları için kullanılacak arama kalıpları.
# Bunlar kaynak keşif ipuçlarıdır; doğrulanmış adres değildir.
ARAMA_SABLONLARI = [
    "{il} yerel haber",
    "{il} son dakika haberleri",
    "{il} belediyesi duyurular",
    "{il} valiliği duyurular",
    "{il} kaymakamlığı duyurular",
    "{il} adliyesi basın açıklaması",
    "{il} barosu duyurular",
]

KATEGORILER = [
    "yerel_basın",
    "belediye",
    "valilik",
    "kaymakamlik",
    "adliye",
    "baro",
    "kamu_duyurusu",
]


def simdi():
    return datetime.now(timezone.utc).isoformat()


def oku_json(dosya, varsayilan):
    if not dosya.exists():
        return varsayilan
    try:
        with dosya.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        raise RuntimeError(
            f"{dosya.name} okunamadı. Dosyayı korumak için işlem durduruldu."
        )


def kaydet_json(dosya, veri):
    gecici = dosya.with_suffix(dosya.suffix + ".tmp")
    with gecici.open("w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)
    gecici.replace(dosya)


def kaynak_listesi(veri):
    if isinstance(veri, list):
        return veri

    if isinstance(veri, dict):
        for anahtar in ("kaynaklar", "sources", "items"):
            if isinstance(veri.get(anahtar), list):
                return veri[anahtar]

    raise RuntimeError(
        "kaynaklar.json içinde tanınan bir kaynak listesi bulunamadı. "
        "Dosya değiştirilmedi."
    )


def kaynak_url(kaynak):
    if not isinstance(kaynak, dict):
        return ""
    return (
        kaynak.get("url")
        or kaynak.get("adres")
        or kaynak.get("link")
        or ""
    ).strip()


def kimlik_uret(url):
    return "mihver-" + hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()[:20]


def il_adi_duzelt(il):
    return il.strip()


def aday_kaynak(il, arama, kategori):
    """
    Arama ifadesi kaynak URL'si değildir.
    Kaynağı doğrulanmış gibi göstermemek için aday kaydı üretir.
    """
    kimlik = hashlib.sha256(
        f"{il}|{arama}|{kategori}".encode("utf-8")
    ).hexdigest()[:20]

    return {
        "id": f"aday-{kimlik}",
        "ad": f"{il} - {kategori.replace('_', ' ').title()} kaynak keşfi",
        "il": il,
        "ilce": None,
        "kategori": kategori,
        "arama_ifadesi": arama,
        "durum": "aday",
        "dogrulandi": False,
        "otomatik_haber_toplama": False,
        "kaynak_turu": "kesif_adayi",
        "olusturulma": simdi()
    }


def ilce_envanteri_olustur():
    """
    İlçe isimleri resmî bir veri kaynağından çekilmeden
    uydurulmaz. Bu fonksiyon 81 il için ilçe envanteri
    alanlarını hazırlar.
    """
    return [
        {
            "il": il,
            "ilceler": [],
            "ilce_listesi_durumu": "resmi_veri_bekleniyor"
        }
        for il in ILLER
    ]


def ana():
    mevcut_veri = oku_json(SOURCES_FILE, [])
    mevcut = kaynak_listesi(mevcut_veri)

    mevcut_urller = {
        kaynak_url(k).rstrip("/").lower()
        for k in mevcut
        if kaynak_url(k)
    }

    adaylar = []
    for il in ILLER:
        for sablon in ARAMA_SABLONLARI:
            arama = sablon.format(il=il)
            kategori = (
                "yerel_basın" if "haber" in arama
                else "belediye" if "belediye" in arama
                else "valilik" if "valilik" in arama
                else "kaymakamlik" if "kaymakamlık" in arama
                else "adliye" if "adliye" in arama
                else "baro" if "baro" in arama
                else "kamu_duyurusu"
            )
            adaylar.append(aday_kaynak(il, arama, kategori))

    # Mevcut kaynak kayıtlarına dokunulmaz.
    # Sadece URL'si olan kayıtlar mevcut kaynak kabul edilir.
    yeni_kayitlar = []
    for aday in adaylar:
        arama_anahtari = (
            aday["il"].casefold(),
            aday["arama_ifadesi"].casefold()
        )

        zaten_var = any(
            isinstance(k, dict)
            and k.get("il", "").casefold() == arama_anahtari[0]
            and k.get("arama_ifadesi", "").casefold() == arama_anahtari[1]
            for k in mevcut
        )

        if not zaten_var:
            yeni_kayitlar.append(aday)

    # Eski JSON biçimini koru.
    if isinstance(mevcut_veri, list):
        yeni_veri = mevcut_veri + yeni_kayitlar
    else:
        yeni_veri = dict(mevcut_veri)
        anahtar = next(
            (k for k in ("kaynaklar", "sources", "items")
             if isinstance(yeni_veri.get(k), list)),
            "kaynaklar"
        )
        yeni_veri[anahtar] = mevcut + yeni_kayitlar

    kaydet_json(SOURCES_FILE, yeni_veri)

    rapor = {
        "proje": "MİHVER",
        "surum": "2.0.0",
        "olusturulma": simdi(),
        "il_sayisi": len(ILLER),
        "ilce_hedefi": 922,
        "ilce_listesi_durumu": "resmi_veri_entegrasyonu_bekleniyor",
        "arama_adayi_sayisi": len(adaylar),
        "yeni_aday_sayisi": len(yeni_kayitlar),
        "mevcut_kaynak_sayisi": len(mevcut),
        "toplam_kayit_sayisi": len(mevcut) + len(yeni_kayitlar),
        "not": (
            "Oluşturulan kayıtlar arama adaylarıdır; doğrulanmış "
            "yayıncı veya haber kaynağı değildir. İlçe listesi "
            "resmî veriden ayrıca alınmalıdır."
        )
    }

    kaydet_json(REPORT_FILE, rapor)

    print("MİHVER kaynak envanteri tamamlandı.")
    print(f"İl sayısı: {len(ILLER)}")
    print(f"İlçe hedefi: 922")
    print(f"Yeni keşif adayı: {len(yeni_kayitlar)}")
    print(f"Toplam kaynak kaydı: {len(mevcut) + len(yeni_kayitlar)}")
    print(f"Rapor: {REPORT_FILE.name}")


if __name__ == "__main__":
    ana()
