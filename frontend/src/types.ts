export interface Transaction {
  id: string;
  user_ref: string;
  amount: number;
  currency: string;
  country: string;
  merchant: string | null;
  status: "pending" | "clear" | "challenged" | "flagged";
  risk_score: number;
  risk_reasons: Record<string, string>;
  created_at: string;
  scored_at: string | null;
  ml_score: number;
  ml_tier: "clean" | "challenge" | "block";
  ml_model_version: string | null;
  reviewed_status: "unreviewed" | "confirmed_fraud" | "false_positive";
  reviewed_by: string | null;
  reviewed_at: string | null;
}

export interface FraudRule {
  id: string;
  name: string;
  description: string | null;
  rule_type: "velocity" | "geo_spread" | "amount_threshold";
  threshold: number;
  window_seconds: number;
  weight: number;
  enabled: boolean;
  updated_at: string;
  updated_by: string | null;
}

export interface MLExplanation {
  available: boolean;
  reason?: string;
  ml_score?: number;
  ml_tier?: string;
  model_version?: string | null;
  top_contributing_features?: Record<string, number>;
  raw_features?: Record<string, number>;
}

export interface CurrentUser {
  email: string;
  role: "analyst" | "compliance_admin";
  organization_name: string;
  organization_id: string;
}
