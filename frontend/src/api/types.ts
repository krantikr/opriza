/** Mirrors the Pydantic response models in `backend/app/schemas`. */

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ActionResult {
  ok: boolean;
  detail: string;
  quotation_id: number | null;
  status: string | null;
  warnings: string[];
}

export type QuotationStatus =
  | "NEW"
  | "PROCESSING"
  | "NEEDS_INFORMATION"
  | "READY_FOR_REVIEW"
  | "EDITED"
  | "APPROVED"
  | "SENT"
  | "REJECTED"
  | "FAILED"
  | "CUSTOMER_ACCEPTED"
  | "CUSTOMER_DECLINED";

export type ReplyIntent = "ACCEPTED" | "DECLINED" | "NEEDS_REVIEW";

export type MatchStatus = "PENDING" | "MATCH_FOUND" | "MULTIPLE_MATCHES" | "NO_MATCH";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";

export interface Attachment {
  id: number;
  filename: string;
  mime_type: string | null;
  size_bytes: number | null;
  has_text: boolean;
  extraction_error: string | null;
}

export interface Email {
  id: number;
  message_id: string;
  source: string;
  sender_email: string | null;
  sender_name: string | null;
  subject: string | null;
  snippet: string | null;
  received_at: string | null;
  category: string | null;
  classification_confidence: number | null;
  classification_reason: string | null;
  processing_status: string;
  processing_ms: number | null;
  error_message: string | null;
  has_attachments: boolean;
  quotation_id: number | null;
  quotation_number: string | null;
  replied_to_quotation_id: number | null;
  reply_intent: ReplyIntent | null;
  reply_intent_confidence: number | null;
  reply_intent_reason: string | null;
  body_text?: string | null;
  attachments?: Attachment[];
}

export interface AvailabilityStep {
  id: string;
  label: string;
  reason: string;
  applied: boolean;
}

export interface StockAvailability {
  available_qty_mt: string | null;
  available_nop: number | null;
  sufficient: boolean | null;
  locations: { location: string | null; balance_qty_mt: number }[];
  ageing_min_days: number | null;
  ageing_max_days: number | null;
  lot_count: number;
  suggested_rate: string | null;
  currency: string;
  unit: string;
  confidence: Confidence | null;
  requires_manual_review: boolean;
  rules_version: string | null;
  explanation: string | null;
  breakdown: AvailabilityStep[];
  stock_as_of: string | null;
}

export interface MatchCandidate {
  stock_item_id: number;
  display_name: string;
  score: number;
  lot_count: number;
  fields: { field: string; awarded: number; weight: number; note: string }[];
}

export interface LineItem {
  id: number;
  line_no: number;
  raw_text: string | null;
  product_type: string | null;
  grade: string | null;
  standard: string | null;
  thickness_mm: number | null;
  width_mm: number | null;
  length_mm: number | null;
  diameter_mm: number | null;
  quantity: string | null;
  quantity_unit: string;
  quantity_mt: string | null;
  conversion_basis: string | null;
  remarks: string | null;
  match_status: MatchStatus;
  match_score: number | null;
  matched_stock_item_id: number | null;
  matched_stock_item_name: string | null;
  match_candidates: MatchCandidate[];
  stock_availability: StockAvailability | null;
}

export interface Draft {
  id: number;
  version: number;
  is_current: boolean;
  subject: string | null;
  body: string | null;
  status: string;
  generated_by: string | null;
  created_at: string;
}

export interface ApprovalRecord {
  id: number;
  action: string;
  comments: string | null;
  was_edited: boolean;
  acted_at: string | null;
  user_name: string | null;
}

export interface FollowUp {
  id: number;
  subject: string | null;
  body: string | null;
  sent: boolean;
  sent_message_id: string | null;
  error: string | null;
  created_at: string;
  user_name: string | null;
}

export interface Quotation {
  id: number;
  quotation_number: string;
  email_id: number;
  customer_id: number | null;
  customer_name: string | null;
  customer_company: string | null;
  customer_email: string | null;
  status: QuotationStatus;
  confidence: Confidence | null;
  delivery_location: string | null;
  line_count: number;
  total_suggested_value: string | null;
  headline_product: string | null;
  headline_availability: string | null;
  requires_manual_review: boolean;
  created_at: string;
  sent_at: string | null;
}

export interface QuotationDetail extends Quotation {
  required_delivery_date: string | null;
  payment_terms: string | null;
  additional_requirements: string[];
  missing_information: string[];
  review_notes: string | null;
  send_error: string | null;
  email: Email | null;
  replies: Email[];
  line_items: LineItem[];
  current_draft: Draft | null;
  drafts: Draft[];
  approvals: ApprovalRecord[];
  follow_ups: FollowUp[];
}

export interface StockItem {
  id: number;
  product_type: string | null;
  grade: string | null;
  thickness_mm: number | null;
  width_mm: number | null;
  length_mm: number | null;
  diameter_mm: number | null;
  location: string | null;
  make: string | null;
  coil_no: string | null;
  nop: number | null;
  qty_kg: string | null;
  balance_nop: number | null;
  balance_qty_kg: string | null;
  purchase_rate_per_kg: number | null;
  landed_cost_per_kg: number | null;
  ageing_days: number | null;
  stock_date: string | null;
  curr_dt: string | null;
  display_name: string;
}

export interface StockSummary {
  product_type: string | null;
  grade: string | null;
  thickness_mm: number | null;
  width_mm: number | null;
  length_mm: number | null;
  display_name: string;
  lot_count: number;
  balance_qty_mt: string;
  balance_nop: number;
  locations: string[];
  ageing_min_days: number | null;
  ageing_max_days: number | null;
  avg_landed_cost_per_kg: number | null;
  /** The underlying rows, so a spec can be expanded to per-lot detail. */
  lots: StockItem[];
}

export interface Customer {
  id: number;
  customer_code: string | null;
  name: string;
  email: string | null;
  phone: string | null;
  company: string | null;
  default_delivery_location: string | null;
  tier: string;
  payment_terms: string | null;
  status: string;
  /** False for records built from an email signature and not yet confirmed. */
  is_verified: boolean;
}

export interface DashboardMetrics {
  emails: {
    total: number;
    pending: number;
    processed: number;
    skipped: number;
    failed: number;
    quotation_requests: number;
    by_category: Record<string, number>;
    avg_processing_ms: number | null;
  };
  quotations: {
    total: number;
    pending_approval: number;
    needs_information: number;
    approved: number;
    sent: number;
    rejected: number;
    failed: number;
    replied: number;
    by_status: Record<string, number>;
    by_confidence: Record<string, number>;
    total_suggested_value: string | null;
  };
  approvals: {
    decisions: number;
    approved: number;
    rejected: number;
    edited: number;
    approval_rate: number | null;
    edit_rate: number | null;
  };
  llm: {
    calls?: number;
    total_tokens?: number;
    total_cost_usd?: number;
    avg_latency_ms?: number;
    failures?: number;
    by_task?: { task: string; calls: number; tokens: number; cost_usd: number }[];
  };
  recent_activity: {
    entity_type: string;
    entity_id: number | null;
    action: string;
    detail: string | null;
    at: string;
  }[];
  generated_at: string;
}

export interface SystemStatus {
  app_name: string;
  environment: string;
  database: string;
  email_source: string;
  email_source_available: boolean;
  llm_configured: boolean;
  llm_models: Record<string, string>;
  auto_send_enabled: boolean;
  rules_version: string;
  stock_lots: number;
  stock_specs: number;
  customers: number;
}

export interface AuditEntry {
  id: number;
  entity_type: string;
  entity_id: number | null;
  action: string;
  details: Record<string, unknown> | null;
  user_id: number | null;
  created_at: string;
}
