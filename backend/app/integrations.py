"""Google Ads + Meta Marketing API clients.

Real SDK calls when credentials are configured; otherwise a stub that returns the exact
request it *would* send (logged by the calling agent). No code changes needed to go live:
fill the env vars in backend/.env.

Metrics never come from here in sandbox mode: test accounts don't serve, so sim.py does.
"""
import uuid
from datetime import datetime, timedelta, timezone

from . import settings

META_API_VERSION = settings.env("META_API_VERSION", "v25.0")


def _result(mode: str, request: dict, response=None, error: str | None = None, id_: str | None = None) -> dict:
    return {"mode": mode, "id": id_, "request": request, "response": response, "error": error}


def _run(configured: bool, platform: str, request: dict, live_fn) -> dict:
    if not configured:
        return _result("stub", request, id_=f"stub-{platform}-{uuid.uuid4().hex[:8]}")
    try:
        id_, resp = live_fn()
        return _result("live", request, response=resp, id_=id_)
    except Exception as e:  # surface API errors to the decision log instead of crashing the cycle
        return _result("error", request, error=f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------ Google
class GoogleAds:
    keys = ["GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
            "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_CUSTOMER_ID"]

    def __init__(self):
        self.configured = all(settings.env(k) for k in self.keys)
        self.customer_id = settings.env("GOOGLE_ADS_CUSTOMER_ID").replace("-", "")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from google.ads.googleads.client import GoogleAdsClient
            self._client = GoogleAdsClient.load_from_dict({
                "developer_token": settings.env("GOOGLE_ADS_DEVELOPER_TOKEN"),
                "client_id": settings.env("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": settings.env("GOOGLE_ADS_CLIENT_SECRET"),
                "refresh_token": settings.env("GOOGLE_ADS_REFRESH_TOKEN"),
                "login_customer_id": settings.env("GOOGLE_ADS_LOGIN_CUSTOMER_ID").replace("-", "") or None,
                "use_proto_plus": True,
            })
        return self._client

    def create_campaign(self, name: str, daily_budget: float) -> dict:
        req = {"customer_id": self.customer_id, "campaign": {
            "name": name, "status": "PAUSED", "advertising_channel_type": "SEARCH",
            "bidding": "MAXIMIZE_CONVERSION_VALUE", "budget_amount_micros": int(daily_budget * 1e6)}}

        def live():
            c = self.client
            bop = c.get_type("CampaignBudgetOperation")
            b = bop.create
            b.name = f"{name} budget {uuid.uuid4().hex[:6]}"
            b.amount_micros = int(daily_budget * 1e6)
            b.delivery_method = c.enums.BudgetDeliveryMethodEnum.STANDARD
            b.explicitly_shared = False
            budget_rn = c.get_service("CampaignBudgetService").mutate_campaign_budgets(
                customer_id=self.customer_id, operations=[bop]).results[0].resource_name

            cop = c.get_type("CampaignOperation")
            camp = cop.create
            camp.name = name
            camp.status = c.enums.CampaignStatusEnum.PAUSED
            camp.advertising_channel_type = c.enums.AdvertisingChannelTypeEnum.SEARCH
            camp.campaign_budget = budget_rn
            c.copy_from(camp.maximize_conversion_value, c.get_type("MaximizeConversionValue"))
            camp.network_settings.target_google_search = True
            try:  # required field in recent API versions
                camp.contains_eu_political_advertising = (
                    c.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING)
            except AttributeError:
                pass
            camp_rn = c.get_service("CampaignService").mutate_campaigns(
                customer_id=self.customer_id, operations=[cop]).results[0].resource_name
            return f"{camp_rn};{budget_rn}", {"campaign": camp_rn, "budget": budget_rn}

        return _run(self.configured, "google", req, live)

    def update_budget(self, platform_id: str, daily_budget: float) -> dict:
        budget_rn = platform_id.split(";")[-1]
        req = {"budget": budget_rn, "amount_micros": int(daily_budget * 1e6)}

        def live():
            from google.api_core import protobuf_helpers
            c = self.client
            op = c.get_type("CampaignBudgetOperation")
            op.update.resource_name = budget_rn
            op.update.amount_micros = int(daily_budget * 1e6)
            c.copy_from(op.update_mask, protobuf_helpers.field_mask(None, op.update._pb))
            c.get_service("CampaignBudgetService").mutate_campaign_budgets(
                customer_id=self.customer_id, operations=[op])
            return platform_id, {"ok": True}

        return _run(self.configured, "google", req, live)

    def budget_recommendations(self) -> list[dict]:
        """MOVE_UNUSED_BUDGET / MARGINAL_ROI_CAMPAIGN_BUDGET hints (empty in stub mode)."""
        if not self.configured:
            return []
        q = ("SELECT recommendation.resource_name, recommendation.type, recommendation.campaign "
             "FROM recommendation WHERE recommendation.type IN "
             "('MOVE_UNUSED_BUDGET', 'MARGINAL_ROI_CAMPAIGN_BUDGET')")
        try:
            svc = self.client.get_service("GoogleAdsService")
            return [{"type": r.recommendation.type_.name, "campaign": r.recommendation.campaign}
                    for r in svc.search(customer_id=self.customer_id, query=q)]
        except Exception as e:
            return [{"error": str(e)}]

    def upload_conversions(self, events: list[dict]) -> dict:
        """Data Manager API events:ingest (OCI via Google Ads API is closed since Jun 2026).
        The OAuth refresh token needs the https://www.googleapis.com/auth/datamanager scope."""
        body = {
            "destinations": [{
                "operatingAccount": {"accountType": "GOOGLE_ADS", "accountId": self.customer_id},
                "productDestinationId": settings.env("GOOGLE_CONVERSION_ACTION_ID"),
            }],
            "encoding": "HEX",
            "events": events,
        }
        if settings.MODE == "sandbox":
            return _result("sandbox", body, id_="logged")

        def live():
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2.credentials import Credentials
            creds = Credentials(None, refresh_token=settings.env("GOOGLE_ADS_REFRESH_TOKEN"),
                                client_id=settings.env("GOOGLE_ADS_CLIENT_ID"),
                                client_secret=settings.env("GOOGLE_ADS_CLIENT_SECRET"),
                                token_uri="https://oauth2.googleapis.com/token",
                                scopes=["https://www.googleapis.com/auth/datamanager"])
            r = AuthorizedSession(creds).post("https://datamanager.googleapis.com/v1/events:ingest", json=body)
            r.raise_for_status()
            return "ingested", r.json()

        return _run(self.configured, "google", body, live)


# ------------------------------------------------------------------ Meta
class MetaAds:
    keys = ["META_APP_ID", "META_APP_SECRET", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"]

    def __init__(self):
        self.configured = all(settings.env(k) for k in self.keys)
        self.account_id = settings.env("META_AD_ACCOUNT_ID").removeprefix("act_")
        self._init = False

    def _api(self):
        if not self._init:
            from facebook_business.api import FacebookAdsApi
            FacebookAdsApi.init(settings.env("META_APP_ID"), settings.env("META_APP_SECRET"),
                                settings.env("META_ACCESS_TOKEN"))
            self._init = True

    def create_campaign(self, name: str, daily_budget: float, days: int) -> dict:
        start = datetime.now(timezone.utc) + timedelta(hours=1)
        # Unified Advantage+ structure: campaign-level budget (Advantage+ campaign budget) +
        # value optimization. ASC/AAC create endpoints are gone from v25; Meta reports the
        # resulting state back in `advantage_state_info`.
        params = {
            "name": name,
            "objective": "OUTCOME_SALES",
            "status": "PAUSED",
            "special_ad_categories": ["FINANCIAL_PRODUCTS_SERVICES"],
            "buying_type": "AUCTION",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "lifetime_budget": int(daily_budget * days * 100),  # cents
            "start_time": start.isoformat(),
            "stop_time": (start + timedelta(days=days)).isoformat(),
        }

        def live():
            from facebook_business.adobjects.adaccount import AdAccount
            self._api()
            camp = AdAccount(f"act_{self.account_id}").create_campaign(params=params)
            return camp["id"], {"id": camp["id"]}

        return _run(self.configured, "meta", {"account": f"act_{self.account_id}", "params": params}, live)

    def update_budget(self, platform_id: str, lifetime_budget: float) -> dict:
        params = {"lifetime_budget": int(lifetime_budget * 100)}

        def live():
            from facebook_business.adobjects.campaign import Campaign
            self._api()
            Campaign(platform_id).api_update(params=params)
            return platform_id, {"ok": True}

        return _run(self.configured, "meta", {"campaign": platform_id, "params": params}, live)

    def upload_conversions(self, events: list[dict]) -> dict:
        """Conversions API offline events into a dataset."""
        dataset = settings.env("META_DATASET_ID")
        req = {"dataset": dataset, "data": events}
        if settings.MODE == "sandbox":
            return _result("sandbox", req, id_="logged")

        def live():
            import requests
            r = requests.post(f"https://graph.facebook.com/{META_API_VERSION}/{dataset}/events",
                              json={"data": events, "access_token": settings.env("META_ACCESS_TOKEN")}, timeout=30)
            r.raise_for_status()
            return "ingested", r.json()

        return _run(self.configured and bool(dataset), "meta", req, live)


google = GoogleAds()
meta = MetaAds()
