"""CVE / vulnerability lookup tool — NIST NVD 2.0 + CISA KEV.

Two public, no-auth federal data sources:

  * NIST NVD 2.0 API
      https://services.nvd.nist.gov/rest/json/cves/2.0
      Returns the canonical record for a CVE: description, CVSS scores,
      affected configurations (CPE), references. Rate limit (no key):
      5 requests / 30 sec. With a free API key you get 50/30s.

  * CISA Known Exploited Vulnerabilities (KEV) catalog
      https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
      Single JSON file. Updated daily. Lists CVEs that have confirmed
      active exploitation in the wild — the ones federal agencies are
      mandated to patch first.

We cache the KEV catalog locally (data/kev_catalog.json) for 24h since
it's ~1 MB and walking it for every search would be wasteful.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
KEV_CACHE = PROJECT_ROOT / "data" / "kev_catalog.json"
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
KEV_CACHE_TTL_S = 24 * 3600   # 24 hours

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 omnigab-cve-tool"
)

CVE_ID_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)


class CveLookupTool:
    name = "cve_lookup"
    description = (
        "Look up vulnerabilities in NIST NVD and the CISA Known Exploited "
        "Vulnerabilities (KEV) catalog. Actions:\n"
        "  * action='cve', cve_id='CVE-2024-3094' — full NVD record\n"
        "  * action='kev_search', keyword='cisco' — search KEV by vendor/product\n"
        "  * action='kev_recent', days=14 — KEV entries added in last N days\n"
        "  * action='is_in_kev', cve_id='CVE-2024-3094' — quick KEV membership test\n"
        "Use this whenever the user mentions a CVE id, asks about exploits, "
        "or wants to know which federal agency must patch what."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["cve", "kev_search", "kev_recent", "is_in_kev"],
            },
            "cve_id": {"type": "string", "description": "e.g. CVE-2024-3094"},
            "keyword": {"type": "string",
                        "description": "Vendor/product substring for kev_search"},
            "days": {"type": "integer",
                     "description": "Lookback window for kev_recent (default 14, max 90)"},
        },
        "required": ["action"],
    }

    # ----- dispatch -----

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").lower().strip()
        if action == "cve":
            return self._lookup_cve(arguments.get("cve_id", ""))
        if action == "kev_search":
            return self._kev_search(arguments.get("keyword", ""))
        if action == "kev_recent":
            try:
                days = max(1, min(90, int(arguments.get("days") or 14)))
            except (TypeError, ValueError):
                days = 14
            return self._kev_recent(days)
        if action == "is_in_kev":
            return self._is_in_kev(arguments.get("cve_id", ""))
        return {"ok": False, "error": f"unknown action: {action}"}

    # ----- NIST NVD lookup -----

    def _lookup_cve(self, cve_id: str) -> dict[str, Any]:
        cve_id = (cve_id or "").strip().upper()
        if not CVE_ID_RE.fullmatch(cve_id):
            return {"ok": False, "error": "cve_id must look like CVE-YYYY-NNNN[N…]"}

        try:
            resp = requests.get(
                NVD_URL,
                params={"cveId": cve_id},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=15,
            )
        except requests.RequestException as exc:
            return {"ok": False, "error": f"NVD request failed: {exc}"}

        if resp.status_code == 403:
            return {"ok": False,
                    "error": "NVD rate limit hit (5 req / 30s without API key). "
                             "Wait 30s or set NVD_API_KEY env var."}
        if resp.status_code != 200:
            return {"ok": False, "error": f"NVD HTTP {resp.status_code}",
                    "body": resp.text[:300]}

        try:
            payload = resp.json()
        except ValueError:
            return {"ok": False, "error": "NVD returned non-JSON"}

        items = payload.get("vulnerabilities") or []
        if not items:
            return {"ok": True, "cve_id": cve_id, "found": False,
                    "note": "No record in NVD for this CVE id."}

        cve = items[0].get("cve", {})
        descriptions = cve.get("descriptions") or []
        desc_en = next((d.get("value", "") for d in descriptions
                        if d.get("lang") == "en"), "")

        # Pull the highest-severity CVSS score available (v3.1 > v3.0 > v2).
        metrics = cve.get("metrics") or {}
        cvss = None
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            arr = metrics.get(key) or []
            if arr:
                primary = arr[0].get("cvssData") or {}
                cvss = {
                    "version": primary.get("version"),
                    "vector": primary.get("vectorString"),
                    "base_score": primary.get("baseScore"),
                    "severity": (arr[0].get("baseSeverity")
                                  or primary.get("baseSeverity")),
                }
                break

        # CWE references (root cause taxonomy).
        cwes = []
        for w in (cve.get("weaknesses") or []):
            for d in (w.get("description") or []):
                if d.get("lang") == "en" and d.get("value", "").startswith("CWE-"):
                    cwes.append(d["value"])

        # Top references (URLs to advisories, patches).
        refs = [r.get("url") for r in (cve.get("references") or [])[:5]
                if r.get("url")]

        # KEV cross-check.
        kev_entry = self._find_in_kev(cve_id)

        return {
            "ok": True,
            "cve_id": cve_id,
            "found": True,
            "published": (cve.get("published") or "")[:10],
            "modified": (cve.get("lastModified") or "")[:10],
            "status": cve.get("vulnStatus"),
            "description": desc_en[:1200],
            "cvss": cvss,
            "cwes": cwes[:5],
            "references": refs,
            "in_kev_catalog": kev_entry is not None,
            "kev_details": kev_entry,
        }

    # ----- CISA KEV catalog -----

    def _load_kev(self) -> dict[str, Any]:
        """Return the parsed KEV catalog, refreshing the cache if stale."""
        KEV_CACHE.parent.mkdir(parents=True, exist_ok=True)
        try:
            stat = KEV_CACHE.stat()
            age = time.time() - stat.st_mtime
        except OSError:
            age = float("inf")

        if age < KEV_CACHE_TTL_S:
            try:
                return json.loads(KEV_CACHE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass   # fall through and re-download

        try:
            resp = requests.get(
                KEV_URL,
                headers={"User-Agent": USER_AGENT},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            KEV_CACHE.write_text(json.dumps(data), encoding="utf-8")
            return data
        except (requests.RequestException, ValueError) as exc:
            # Fall back to stale cache if we have one.
            if KEV_CACHE.exists():
                try:
                    return json.loads(KEV_CACHE.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
            return {"vulnerabilities": [], "_error": str(exc)}

    def _find_in_kev(self, cve_id: str) -> dict[str, Any] | None:
        catalog = self._load_kev()
        for entry in catalog.get("vulnerabilities") or []:
            if entry.get("cveID", "").upper() == cve_id.upper():
                return {
                    "vendor": entry.get("vendorProject"),
                    "product": entry.get("product"),
                    "name": entry.get("vulnerabilityName"),
                    "date_added": entry.get("dateAdded"),
                    "due_date": entry.get("dueDate"),
                    "required_action": entry.get("requiredAction"),
                    "ransomware_use_known": entry.get("knownRansomwareCampaignUse"),
                }
        return None

    def _is_in_kev(self, cve_id: str) -> dict[str, Any]:
        cve_id = (cve_id or "").strip().upper()
        if not CVE_ID_RE.fullmatch(cve_id):
            return {"ok": False, "error": "cve_id must look like CVE-YYYY-NNNN"}
        entry = self._find_in_kev(cve_id)
        return {
            "ok": True,
            "cve_id": cve_id,
            "in_kev": entry is not None,
            "details": entry,
        }

    def _kev_search(self, keyword: str) -> dict[str, Any]:
        keyword = (keyword or "").strip().lower()
        if not keyword:
            return {"ok": False, "error": "keyword required"}
        catalog = self._load_kev()
        matches = []
        for entry in catalog.get("vulnerabilities") or []:
            haystack = " ".join([
                entry.get("vendorProject", ""),
                entry.get("product", ""),
                entry.get("vulnerabilityName", ""),
                entry.get("shortDescription", ""),
                entry.get("cveID", ""),
            ]).lower()
            if keyword in haystack:
                matches.append({
                    "cve_id": entry.get("cveID"),
                    "vendor": entry.get("vendorProject"),
                    "product": entry.get("product"),
                    "name": entry.get("vulnerabilityName"),
                    "date_added": entry.get("dateAdded"),
                    "due_date": entry.get("dueDate"),
                    "ransomware_use_known": entry.get("knownRansomwareCampaignUse"),
                })
                if len(matches) >= 25:
                    break
        return {
            "ok": True,
            "keyword": keyword,
            "match_count": len(matches),
            "matches": matches,
            "catalog_total": len(catalog.get("vulnerabilities") or []),
        }

    def _kev_recent(self, days: int) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        catalog = self._load_kev()
        recent = []
        for entry in catalog.get("vulnerabilities") or []:
            added = entry.get("dateAdded") or ""
            try:
                added_date = datetime.strptime(added, "%Y-%m-%d").date()
            except ValueError:
                continue
            if added_date >= cutoff:
                recent.append({
                    "cve_id": entry.get("cveID"),
                    "vendor": entry.get("vendorProject"),
                    "product": entry.get("product"),
                    "name": entry.get("vulnerabilityName"),
                    "date_added": entry.get("dateAdded"),
                    "due_date": entry.get("dueDate"),
                    "ransomware_use_known": entry.get("knownRansomwareCampaignUse"),
                })
        recent.sort(key=lambda x: x["date_added"] or "", reverse=True)
        return {
            "ok": True,
            "days": days,
            "cutoff_date": cutoff.isoformat(),
            "count": len(recent),
            "entries": recent,
        }
