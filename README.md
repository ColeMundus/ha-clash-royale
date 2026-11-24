<img src="https://raw.githubusercontent.com/ColeMundus/ha-clash-royale/main/custom_components/clash_royale/brand/icon.png" alt="Clash Royale" width="96">

# Clash Royale for Home Assistant

[![CI: workflow](docs/badges/ci.svg)](https://github.com/ColeMundus/ha-clash-royale/actions/workflows/ci.yml)
[![HA tested: 2026.11.0](docs/badges/compatibility.svg)](https://github.com/ColeMundus/ha-clash-royale/actions/workflows/ci.yml)
[![License: MIT](docs/badges/license.svg)](LICENSE)
[![Distribution: HACS custom](docs/badges/distribution.svg)](#installation)

Player, current-clan and River Race sensors using Supercell's official API. Enter a player tag once; the integration follows that player's current clan automatically.

## Installation

Requires **Home Assistant Core 2026.11.0 or newer**.

1. Search for **Clash Royale** in HACS or **Settings → Marketplace**.
2. If it is not listed yet, add `https://github.com/ColeMundus/ha-clash-royale` as a custom repository with category **Integration**. In the Marketplace, choose **Add from link** and connect GitHub if prompted.
3. Choose **Install**, and restart Home Assistant when prompted. No pre-release setting is needed.
4. Open **Settings → Devices & services → Add integration → Clash Royale**.

**Manual install:** Download the [release ZIP](https://github.com/ColeMundus/ha-clash-royale/releases/download/v0.1.3/clash_royale-0.1.3.zip), extract it into your Home Assistant configuration directory, and restart.

## Create an API key

1. Sign in at the [Clash Royale developer portal](https://developer.clashroyale.com/).
2. Open **My Account → Create New Key** and enter a name and description.
3. Under **Allowed IP addresses**, enter the public IP address used by Home Assistant's outbound requests. Developer keys are IP-bound; update the key if that address changes.
4. Create the key, then paste its **Token** into the integration's **API token** field and enter your in-game **Player tag**.

Only the API token and player tag are required. Add another integration entry to monitor another player. Polling defaults to five minutes and is adjustable from 1–60 minutes through **Configure**.

![Clash Royale setup in Home Assistant](docs/images/setup.png)

## Sensors

| Group | Sensors |
| --- | --- |
| Player | Trophies, best trophies, XP level, XP points, wins, losses, battle count, donations, donations received |
| Current clan | Clan members, clan score, clan war trophies |
| Clan River Race | River race fame, River race repair points |
| Player River Race | Player race fame, player race repair points, player race boat attacks, player race decks used, player race decks used today |

Player race fame is the player's reported medals; clan River Race fame is clan progress or Colosseum score, not the sum of player medals. No race rank is exposed.

## Limitations

- Data is polled, not live. Players without a clan and missing optional River Race data leave the corresponding sensors unavailable, not zero.
- The API does not expose chest queues, upgrade timers or resource balances. Decks used today is a reported count, not a remaining-attacks estimate or a reset countdown.

This unofficial integration is not affiliated with Supercell and is not endorsed by Supercell. Clash Royale artwork belongs to Supercell; see [NOTICE.md](NOTICE.md). See Supercell's [Fan Content Policy](https://supercell.com/en/fan-content-policy/).

<!-- Temporary CI measurement full-07. This PR will be closed unmerged. -->
