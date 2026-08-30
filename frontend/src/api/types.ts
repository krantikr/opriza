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
  | "CUSTOMER_DECLINED"
  | "NEGOTIATION"
  | "PAYMENT_PENDING"
  | "PAID";

/** The six working stages, in the order a desk reads them. */
export type QuotationStage =
  | "received"
  | "sent"
  | "negotiation"
  | "delivery_pending"
  | "payment_pending"
  | "completed";

export type NotSentReason =
  | "PENDING_MARKET_RATE"
  | "PENDING_CUSTOMER_RATE"
  | "PENDING_HEAD_APPROVAL"
  | "OTHER";

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
  quotation_status: string | null;
  follow_up_due: boolean;
  follow_up_at: string | null;
  /** The single pending stage this message is at, or DONE. */
  state:
    | "ENQUIRY"
    | "FOLLOW_UP"
    | "NEEDS_REPLY"
    | "DELIVERY"
    | "COMPLAINT"
    | "DONE";
  promised_date_raw: string | null;
  promised_date: string | null;
  awaiting_us: boolean;
  answered_at: string | null;
  replied_to_quotation_id: number | null;
  reply_intent: ReplyIntent | null;
  reply_intent_confidence: number | null;
  reply_intent_reason: string | null;
  body_text?: string | null;
  attachments?: Attachment[];
}

export interface LineItemPricing {
  /** Present once the line has been priced by the rule engine. */
  pricing?: QuotationPricing | null;
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
  on_hand_qty_mt: string | null;
  reserved_qty_mt: string | null;
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
  matched_stock_item_make: string | null;
  match_candidates: MatchCandidate[];
  stock_availability: StockAvailability | null;
  pricing: QuotationPricing | null;
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
  /** The working stage this status derives to, or null once a deal is lost
   *  / rejected and has nothing left to work. Computed server-side. */
  stage: QuotationStage | null;
  confidence: Confidence | null;
  delivery_location: string | null;
  line_count: number;
  total_suggested_value: string | null;
  headline_product: string | null;
  headline_availability: string | null;
  requires_manual_review: boolean;
  not_sent_reason: NotSentReason | null;
  not_sent_note: string | null;
  is_priority_customer: boolean;
  is_priority_product: boolean;
  line_items: LineItem[];
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
  /** True if any lot in this spec is a flagged grade+make - a spec can span
   *  more than one mill, so this is "at least one priority lot", not "all". */
  is_priority: boolean;
  /** The underlying rows, so a spec can be expanded to per-lot detail. */
  lots: StockItem[];
}

export interface PriorityProduct {
  id: number;
  grade: string;
  make: string;
}

export interface StockImportResult {
  status: string;
  source_file: string;
  rows_total: number;
  rows_imported: number;
  rows_failed: number;
  rows_skipped: number;
  errors: { row?: number; error?: string }[];
  batch_id: number | null;
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
  is_priority: boolean;
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
  pricing_version: number | null;
  stock_lots: number;
  stock_specs: number;
  customers: number;
  /** When this desk's mailbox was last checked. Null before the first poll. */
  last_polled_at: string | null;
  /** The cadence in force right now, in the poller's own words. */
  poll_reason: string | null;
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

/* ---------------------------------------------------------------------------
   Pricing
   --------------------------------------------------------------------------- */

export type PricingComponentKind =
  | "BASE_PRICE"
  | "TRANSPORTATION"
  | "HANDLING"
  | "FINANCING"
  | "RISK_BUFFER"
  | "INVOICE_ANCHOR"
  | "QUANTITY_SLAB"
  | "CUSTOMER_TIER"
  | "ADJUSTMENT"
  | "TARGET_MARGIN"
  | "MARGIN_FLOOR"
  | "ROUNDING";

export type PricingBasis = "STOCK" | "MILL_OFFER" | "MANUAL" | "UNAVAILABLE";

export interface PricingComponent {
  code: string;
  label: string;
  kind: PricingComponentKind;
  amount: string;
  note: string;
  applied: boolean;
  overridden: boolean;
  computed_amount: string | null;
  subtotal: string | null;
  meta: Record<string, unknown>;
}

export interface QuotationPricing {
  id: number;
  basis: PricingBasis;
  basis_note: string | null;
  base_rate: string | null;
  total_cost: string | null;
  margin_amount: string | null;
  quote_rate: string | null;
  line_total: string | null;
  currency: string;
  quantity_mt: string | null;
  rules_version: number | null;
  components: PricingComponent[];
  explanation: string | null;
  warnings: string[];
  has_overrides: boolean;
  draft_stale: boolean;
  /** Priced against a rule set that is no longer live. */
  rules_stale: boolean;
}

export interface PricingRule {
  id?: number;
  code: string;
  label: string;
  kind: PricingComponentKind;
  priority: number;
  is_active: boolean;
  conditions: Record<string, unknown> | null;
  config: Record<string, unknown>;
  note_template?: string | null;
}

export interface PricingRuleSet {
  id: number;
  version: number;
  label: string | null;
  notes: string | null;
  is_active: boolean;
  published_at: string | null;
  created_at: string;
  rules: PricingRule[];
}

export interface PricingPreview {
  basis: PricingBasis;
  base_rate: string | null;
  total_cost: string | null;
  margin_amount: string | null;
  quote_rate: string | null;
  line_total: string | null;
  currency: string;
  rules_version: number | null;
  components: PricingComponent[];
  explanation: string | null;
  warnings: string[];
}

export interface LocationDistance {
  id: number;
  origin: string;
  destination: string;
  distance_km: number;
  typical_days: number | null;
  notes: string | null;
}

export interface VehicleRate {
  id: number;
  name: string;
  capacity_mt: string;
  rate_per_day: string;
  avg_km_per_day: number;
  min_days: number;
  status: string;
}

/* ---------------------------------------------------------------------------
   Operations
   --------------------------------------------------------------------------- */

export interface FollowUpRule {
  id: number;
  label: string;
  is_active: boolean;
  trigger: "ELAPSED" | "PROMISED_DATE";
  first_after_hours: number;
  remind_before_hours: number;
  first_after_days: number;
  interval_days: number;
  max_attempts: number;
  stop_after_days: number | null;
  auto_send: boolean;
  mark_cold_when_exhausted: boolean;
  conditions: Record<string, unknown> | null;
  subject_template: string | null;
  body_template: string | null;
}

export interface FollowUpSchedule {
  id: number;
  quotation_request_id: number;
  attempt_no: number;
  due_at: string;
  status: string;
  subject: string | null;
  body: string | null;
  resolution_note: string | null;
}

export interface ScoreFactor {
  label: string;
  factor: number;
}

/** One open quotation on the chase board. The row is the quotation, not a
 *  scheduled nudge - a due schedule is only one of the signals that makes it
 *  hot, carried here as `schedule_id`. */
export interface ChaseRow {
  quotation_id: number;
  quotation_number: string;
  turn: "YOURS" | "THEIRS" | "COLD" | "SNOOZED";

  customer_name: string;
  customer_email: string | null;
  contact_name: string | null;
  customer_note: string;
  quotes_total: number;
  quotes_won: number;

  material: string;
  quantity: string;
  quoted_rate: number | null;
  value: number;

  reason: string;
  /** What to do, in the imperative. Replaced a body snippet, which was almost
   *  always the salutation once clamped to the column. */
  next_step: string;

  last_at: string | null;
  last_direction: string | null;
  last_actor: string;
  last_subject: string | null;
  message_count: number;

  sent_at: string | null;
  quote_age_days: number;
  days_waiting: number;
  waiting_note: string;
  chase_until: string | null;
  chase_note: string | null;

  delivery_location: string | null;
  required_by: string | null;
  payment_terms: string | null;

  stock_note: string | null;
  stock_short: boolean;

  promised_date: string | null;
  promised_words: string | null;
  snoozed_until: string | null;
  has_attachment: boolean;
  attempts: number;
  last_chased_at: string | null;
  schedule_id: number | null;

  value_at_risk: number;
  factors: ScoreFactor[];
}

export interface ChaseBoard {
  rows: ChaseRow[];
  counts: Record<string, number>;
  value_awaiting_you: number;
  quiet_over_a_week: number;
}

export type LostReason =
  | "PRICE"
  | "COMPETITOR"
  | "DELAYED"
  | "NO_STOCK"
  | "NO_RESPONSE"
  | "OTHER";

export interface PastInvoice {
  invoice_no: string | null;
  invoice_date: string | null;
  material: string;
  quantity_mt: string | null;
  rate_per_mt: string | null;
  line_total: string | null;
  delivery_location: string | null;
  /** Matches the specification being quoted, so it can anchor a price. */
  same_material: boolean;
}

export interface PastQuotationRow {
  id: number;
  quotation_number: string;
  created_at: string;
  sent_at: string | null;
  status: string;
  material: string;
  quantity_mt: string | null;
  rate_per_mt: string | null;
  value: string | null;
  won: boolean;
  same_material: boolean;
}

export interface PastOrders {
  customer_name: string | null;
  invoices: PastInvoice[];
  quotations: PastQuotationRow[];
  orders_count: number;
  total_value: string | null;
  total_quantity_mt: string | null;
  last_order_at: string | null;
  quotes_count: number;
  quotes_won: number;
  avg_rate_same_material: string | null;
  current_rate: string | null;
  rate_delta: string | null;
}

export interface PushDevice {
  id: number;
  label: string | null;
  user_agent: string | null;
  is_active: boolean;
  last_seen_at: string | null;
  disabled_reason: string | null;
  created_at: string;
}

export interface NotificationRule {
  id: number;
  label: string;
  kind: string;
  channel: string;
  is_active: boolean;
  recipient_user_ids: number[] | null;
  recipient_emails: string[] | null;
  recipient_phones: string[] | null;
  conditions: Record<string, unknown> | null;
}

export interface StockMovement {
  id: number;
  kind: string;
  quantity_kg: string;
  nop: number | null;
  product_type: string | null;
  grade: string | null;
  thickness_mm: number | null;
  location: string | null;
  reference: string | null;
  note: string | null;
  movement_date: string | null;
  is_open: boolean;
  created_at: string;
}

export interface TimelineEntry {
  at: string;
  kind: string;
  title: string;
  detail: string | null;
  link: string | null;
}

export interface ReportResult {
  title: string;
  period: string;
  rows: Record<string, string | number>[];
  totals: Record<string, unknown>;
}

export interface FunnelReport {
  period: string;
  stages: {
    stage: string;
    count: number;
    note: string;
    tonnes: number;
    value: number;
    unquantified: number;
  }[];
}

/* ---------------------------------------------------------------------------
   Trends
   --------------------------------------------------------------------------- */

export interface TrendPoint {
  day: string;
  enquiries: number;
  quotations: number;
  sent: number;
  won: number;
  value: string;
}

export interface TrendDelta {
  key: string;
  label: string;
  current: number;
  previous: number;
  change_pct: number | null;
  direction: "up" | "down" | "flat";
  good: boolean | null;
  unit: string;
}

export interface Trends {
  days: number;
  period_label: string;
  previous_label: string;
  series: TrendPoint[];
  deltas: TrendDelta[];
}

export interface CustomerNote {
  id: number;
  body: string;
  pinned: boolean;
  created_at: string;
}

export interface StockHold {
  id: number;
  kind: string;
  quantity_kg: string;
  product_type: string | null;
  grade: string | null;
  thickness_mm: number | null;
  location: string | null;
  reference: string | null;
  note: string | null;
  movement_date: string | null;
  is_open: boolean;
  created_at: string;
}

/* ---------------------------------------------------------------------------
   Business insights
   --------------------------------------------------------------------------- */

export interface InsightMetric {
  key: string;
  label: string;
  current: number;
  previous: number;
  change_pct: number | null;
  direction: "up" | "down" | "flat";
  good: boolean | null;
  unit: string;
  hint: string;
}

export interface InsightHighlight {
  tone: "good" | "warn" | "bad" | "info";
  title: string;
  detail: string;
  link: string | null;
}

export interface InsightSeriesPoint {
  label: string;
  start: string;
  end: string;
  quotations: number;
  sent: number;
  won: number;
  value: number;
}

export interface InsightCustomer {
  name: string;
  quotations: number;
  value: number;
  won: number;
  lost: number;
  win_rate: number | null;
}

export interface InsightProduct {
  name: string;
  lines: number;
  quantity_mt: number;
  value: number;
  won: number;
}

export interface AttentionRow {
  id: number;
  number: string;
  customer: string;
  status: string;
  value: number;
  age_days: number;
  link: string;
}

export interface Insights {
  period_label: string;
  previous_label: string;
  metrics: InsightMetric[];
  highlights: InsightHighlight[];
  series: InsightSeriesPoint[];
  by_status: { label: string; value: number }[];
  top_customers: InsightCustomer[];
  top_products: InsightProduct[];
  ageing_buckets: { label: string; lots: number; value: number }[];
  attention: AttentionRow[];
}

/* ---------------------------------------------------------------------------
   Desk report — the trading view of a period.

   Activity counts say how busy the desk was; these say whether it made money.
   --------------------------------------------------------------------------- */

export interface DeskMoney {
  revenue: number;
  cost: number;
  profit: number;
  margin_pct: number;
  tonnes: number;
  profit_per_mt: number;
  deals: number;
}

export interface DeskTrendPoint {
  label: string;
  revenue: number;
  profit: number;
  quoted: number;
  tonnes: number;
}

export interface DeskLostReason {
  reason: string;
  label: string;
  action: string;
  count: number;
  value: number;
  profit_missed: number;
}

export interface DeskCustomer {
  customer: string;
  quotes: number;
  won: number;
  lost: number;
  win_rate: number | null;
  quoted_value: number;
  revenue: number;
  profit: number;
  margin_pct: number;
  tonnes: number;
}

export interface DeskProduct {
  product: string;
  lines: number;
  won_lines: number;
  quoted_value: number;
  tonnes_quoted: number;
  tonnes_won: number;
  revenue: number;
  profit: number;
  margin_pct: number;
  profit_per_mt: number;
}

export interface DeskStock {
  buckets: { label: string; lots: number; value: number; tonnes: number }[];
  total_value: number;
  deadstock_value: number;
  deadstock_pct: number;
  deadstock_lots: number;
  oldest: {
    spec: string;
    location: string;
    ageing_days: number;
    tonnes: number;
    value: number;
  }[];
}

export interface DeskDelivery {
  on_time: number;
  late: number;
  on_time_pct: number | null;
  avg_days_late: number;
  overdue_now: number;
}

export interface DeskQuietCustomer {
  customer: string;
  last_seen: string;
  days_quiet: number;
  lifetime_revenue: number;
  lifetime_profit: number;
  orders: number;
}

export interface DeskEnquiries {
  received: number;
  identified: number;
  not_enquiries: number;
  raised: number;
  not_raised: number;
  sent: number;
  not_sent: number;
  awaiting: number;
  won: number;
  lost: number;
  win_rate: number | null;
  conversion_rate: number | null;
}

export interface DeskStockMovement {
  opening_mt: number;
  receipts_mt: number;
  issues_mt: number;
  closing_mt: number;
  receipts_value: number;
  issues_value: number;
  closing_value: number;
  receipt_count: number;
  issue_count: number;
  movements: number;
}

export interface DeskReport {
  period_key: string;
  period_label: string;
  period_range: string;
  previous_label: string;
  grain: string;
  won: DeskMoney;
  won_previous: DeskMoney;
  open_book: DeskMoney;
  quoted: DeskMoney;
  trend: DeskTrendPoint[];
  lost_reasons: DeskLostReason[];
  customers: DeskCustomer[];
  products: DeskProduct[];
  concentration: {
    top_1_pct: number;
    top_3_pct: number;
    top_5_pct: number;
    customers: number;
  };
  stock: DeskStock;
  delivery: DeskDelivery;
  quiet_customers: DeskQuietCustomer[];
  enquiries: DeskEnquiries;
  stock_movement: DeskStockMovement;
}

export interface PeriodChoice {
  key: string;
  label: string;
  range: string;
}

export interface TemplatePlaceholder {
  name: string;
  description: string;
}

export interface EmailTemplates {
  followup_subject_template: string | null;
  followup_body_template: string | null;
  default_followup_subject: string;
  default_followup_body: string;
  placeholders: TemplatePlaceholder[];
}

export interface SpecPosition {
  product_type: string | null;
  grade: string | null;
  thickness_mm: number | null;
  width_mm: number | null;
  length_mm: number | null;
  display_name: string;
  lot_count: number;
  locations: string[];
  in_stock_mt: string;
  committed_mt: string;
  free_mt: string;
  to_buy_mt: string;
  prospective_mt: string;
  cost_per_mt: string | null;
}

export interface StockPosition {
  in_stock_mt: string;
  committed_mt: string;
  free_mt: string;
  to_buy_mt: string;
  prospective_mt: string;
  specs_short: number;
  specs: SpecPosition[];
}

export interface Stage {
  key: string;
  label: string;
  count: number;
  tonnes: number;
  value: number;
}

export interface DeliveryDue {
  quotation_id: number;
  quotation_number: string;
  customer: string;
  material: string;
  tonnes: number;
  value: number;
  wanted_by: string | null;
  in_stock_mt: number;
  to_buy_mt: number;
}

export interface PaymentDue {
  quotation_id: number;
  quotation_number: string;
  customer: string;
  tonnes: number;
  value: number;
  despatched_on: string | null;
  terms: string | null;
  due_on: string | null;
  days_overdue: number;
  bucket: "not_due" | "due_soon" | "overdue";
}

export interface PipelineReport {
  stages: Stage[];
  to_buy_mt: number;
  due_this_week: number;
  overdue_value: number;
  overdue_count: number;
  deliveries: DeliveryDue[];
  payments: PaymentDue[];
  payment_buckets: Stage[];
}
