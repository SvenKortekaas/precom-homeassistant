# Pre-Com — Home Assistant Integratie

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2023.1%2B-blue.svg)](https://www.home-assistant.io)

Home Assistant integratie voor [Pre-Com](https://pre-com.nl) — het plannings- en alarmeringssysteem voor vrijwilligers bij Nederlandse hulpdiensten (brandweer, ambulance, politie).

---

## Functies

### Entiteiten

| Entiteit | Type | Beschrijving |
|---|---|---|
| `switch.pre_com_beschikbaar` | Switch | Beschikbaar / niet beschikbaar melden |
| `number.pre_com_niet_beschikbaar_uren` | Number | Aantal uur voor niet-beschikbaar (standaard 8) |
| `binary_sensor.pre_com_beschikbaar` | Binary Sensor | Huidige beschikbaarheidsstatus |
| `binary_sensor.pre_com_buiten_regio` | Binary Sensor | Buiten regio status |
| `binary_sensor.pre_com_alarm_actief` | Binary Sensor | Onbeantwoord alarm aanwezig |
| `sensor.pre_com_laatste_alarm` | Sensor | Tekst van het meest recente alarm |
| `sensor.pre_com_alarm_aantal` | Sensor | Aantal alarmberichten |
| `sensor.pre_com_volgende_dienst` | Sensor | Eerstvolgende roosterdienst |
| `sensor.pre_com_gebruiker` | Sensor | Ingelogde gebruiker |
| `button.pre_com_vernieuwen` | Button | Haal direct nieuwe data op |

### Events

**`precom_alarm_received`** — Wordt gevuurd bij elk nieuw alarmbericht.

```yaml
# Beschikbare velden in trigger.event.data:
alarm_id: 12345
text: "A1 AMSTERDAM HOOFDSTRAAT 1 BRAND"
time: "2026-03-19T13:42:00"
group: "Brandweer Amsterdam"
type: "Alarm"
capcode: "1234567"
```

### Services

| Service | Parameters | Beschrijving |
|---|---|---|
| `precom.set_available` | `available: true/false`, `hours: 1-168` | Beschikbaarheid instellen |
| `precom.respond_to_alarm` | `alarm_id`, `available` | Reageren op een alarm |
| `precom.set_outside_region` | `hours: 1-168` | Buiten regio melden |

---

## Installatie

### Via HACS (aanbevolen)

1. Ga in Home Assistant naar **HACS → Integraties**
2. Klik op de drie puntjes (⋮) rechtsboven → **Aangepaste repository's**
3. Voer de GitHub URL in van deze repository
4. Kies categorie **Integratie** en klik op **Toevoegen**
5. Zoek naar **Pre-Com** en klik op **Downloaden**
6. Herstart Home Assistant

### Handmatig

1. Kopieer de map `custom_components/precom` naar `/config/custom_components/precom`
2. Herstart Home Assistant

---

## Configuratie

1. Ga naar **Instellingen → Apparaten & Diensten → Integratie toevoegen**
2. Zoek naar **Pre-Com**
3. Vul je e-mailadres en wachtwoord in (zelfde als in de Pre-Com app)
4. Stel de intervalwaarden in (standaard is goed voor de meeste gebruikers)

### Opties (aanpasbaar na installatie)

| Optie | Standaard | Beschrijving |
|---|---|---|
| Verversingsinterval rooster | 300 sec | Hoe vaak rooster en gebruikersinfo opgehaald wordt |
| Alarmcheck interval | 30 sec | Hoe vaak op nieuwe alarmen gecheckt wordt |

---

## Beschikbaarheid beheren

**Beschikbaar melden:** Zet `switch.pre_com_beschikbaar` op **aan**.

**Niet beschikbaar melden:**
1. Stel het aantal uur in via `number.pre_com_niet_beschikbaar_uren`
2. Zet `switch.pre_com_beschikbaar` op **uit**

De integratie plaatst dan een blok in je Pre-Com agenda van nu tot nu + X uur.

**Beschikbaar melden na niet-beschikbaar:** Zet de switch terug op **aan**. De integratie haalt de actuele agenda op en verwijdert het actieve blok automatisch.

---

## Logging inzien

Voeg toe aan `/config/configuration.yaml` voor uitgebreide logging:

```yaml
logger:
  logs:
    custom_components.precom: debug
```

Bekijk daarna via **Instellingen → Systeem → Logboek** (filter op `precom`).

---

## Vereisten

- Home Assistant 2023.1.0 of nieuwer
- Een actief Pre-Com account

---

## Licentie

MIT License
