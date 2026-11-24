"use client";
/** A creative rendered as the ad people will actually see: a search text ad (google) or a
 *  sponsored social post (meta). Copy comes straight from the creative + compliance agents. */
import type { ReactNode } from "react";
import { PRODUCT_COLORS } from "@/lib/api";
import { Chip, type Tone } from "./ui";

export type Creative = {
  id: number; product: string; channel: string; headline: string; body: string; disclosure: string;
  status: string; findings: { severity: string; rule: string; msg: string }[];
};

const STATUS: Record<string, { label: string; tone: Tone }> = {
  approved: { label: "Approved", tone: "good" },
  pending_approval: { label: "Awaiting approval", tone: "attention" },
  rejected: { label: "Rejected", tone: "neutral" },
  failed_compliance: { label: "Failed compliance", tone: "fault" },
};

const PRODUCT_LABEL: Record<string, string> = { checking: "Checking", savings: "Savings", cd: "CD", money_market: "Money market" };

const domainOf = (bank: string) => bank.toLowerCase().replace(/[^a-z0-9]+/g, "") + ".example";
const initials = (bank: string) => bank.split(/\s+/).filter((w) => /^[A-Z]/.test(w)).slice(0, 2).map((w) => w[0]).join("");

export function AdPreview({ ad, bank, productName, apy, select }:
  { ad: Creative; bank: string; productName?: string; apy?: number; select?: ReactNode }) {
  const color = PRODUCT_COLORS[ad.product] ?? "#2470cc";
  const st = STATUS[ad.status] ?? { label: ad.status, tone: "neutral" as Tone };
  const domain = domainOf(bank);

  return (
    <article className="ad">
      <div className="ad-meta">
        {select}
        <span>{ad.channel === "google" ? "Google Search" : ad.channel === "meta" ? "Meta feed" : ad.channel}</span>
        <span>·</span>
        <span>{PRODUCT_LABEL[ad.product] ?? ad.product}</span>
        <Chip tone={st.tone}>{st.label}</Chip>
      </div>

      {ad.channel === "google" ? (
        <div className="ad-search">
          <div className="sponsor">
            <span className="fav" style={{ background: color }}>{initials(bank)}</span>
            <span>
              <div><span className="tag">Sponsored</span> · {bank}</div>
              <div className="url">https://www.{domain}</div>
            </span>
          </div>
          <div className="headline">{ad.headline}</div>
          <div className="body">{ad.body}</div>
        </div>
      ) : (
        <div className="ad-social">
          <div className="top">
            <span className="avatar" style={{ background: color }}>{initials(bank)}</span>
            <span>
              <div className="name">{bank}</div>
              <div className="sponsored">Sponsored</div>
            </span>
          </div>
          <div className="text">{ad.body}</div>
          <div className="visual" style={{ background: `linear-gradient(135deg, ${color}, color-mix(in srgb, ${color} 55%, #000))` }}>
            {apy !== undefined && apy > 0 && <div className="big">{apy.toFixed(2)}% APY</div>}
            <div className="small">{productName ?? PRODUCT_LABEL[ad.product]}</div>
          </div>
          <div className="cta-row">
            <span>
              <div className="domain">{domain}</div>
              <div className="hl">{ad.headline}</div>
            </span>
            <span className="cta">Learn more</span>
          </div>
        </div>
      )}

      <div className="ad-disclosure">{ad.disclosure}</div>
      {(ad.findings?.length > 0 || ad.status !== "rejected") && (
        <div className="ad-findings">
          {ad.findings?.map((f, i) => (
            <div key={i} className={f.severity === "error" ? "err" : "warn"}>
              {f.severity === "error" ? "✖" : "⚠"} {f.rule}: {f.msg}
            </div>
          ))}
          {!ad.findings?.length && <div className="ok">✔ Reg DD and claims checks passed</div>}
        </div>
      )}
    </article>
  );
}
