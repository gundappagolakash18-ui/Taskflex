export type UserRole = "CUSTOMER" | "WORKER" | "ADMIN";

export type TaskStatus =
  | "DRAFT"
  | "PENDING_CONFIRMATION"
  | "CONFIRMED"
  | "SEARCHING_WORKER"
  | "OFFERED"
  | "ACCEPTED"
  | "WORKER_ON_THE_WAY"
  | "ARRIVED_AT_LOCATION"
  | "IN_PROGRESS"
  | "COMPLETION_REQUESTED"
  | "COMPLETED"
  | "CANCELLED"
  | "DISPUTED"
  | "EMERGENCY_ALERT"
  | "QUEUED_NEXT"
  | "SCHEDULED_OPEN"
  | "SCHEDULED_ASSIGNED";

export type TaskType =
  | "document_submission"
  | "queue_standing"
  | "government_office"
  | "document_collection"
  | "courier_pickup"
  | "form_submission"
  | "appointment_assistance"
  | "local_errand"
  | "grocery_pickup"
  | "parcel_collection"
  | "office_errand"
  | "bank_assistance"
  | "college_work"
  | "other";

export type Urgency = "low" | "normal" | "high" | "urgent";

export type WorkerTier = "SILVER" | "GOLD" | "PLATINUM";

export interface AuthUser {
  id: string;
  full_name: string;
  email: string;
  phone: string | null;
  role: UserRole;
  avatar_url: string | null;
  city: string | null;
  is_email_verified: boolean;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface AuthResponse {
  user: AuthUser;
  tokens: TokenPair;
}

export interface RegisterResponse {
  user: AuthUser;
  needs_verification: boolean;
}

export interface UserBrief {
  id: string;
  full_name: string;
  avatar_url: string | null;
  city: string | null;
  role?: string;
  is_verified?: boolean;
  rating_average?: number;
  rating_count?: number;
  completed_tasks_count?: number;
}

export interface TaskRequirement {
  skill_name: string;
  is_required: boolean;
}

export interface Task {
  id: string;
  title: string;
  description: string;
  task_type: TaskType;
  status: TaskStatus;
  urgency: Urgency;
  scheduled_date: string | null;
  scheduled_time: string | null;
  estimated_duration_minutes: number;
  latitude: number | null;
  longitude: number | null;
  address_text: string | null;
  area_name: string | null;
  city: string | null;
  budget: number;
  currency: string;
  special_requirements: string | null;
  parsed_by_ai: boolean;
  ai_confidence: number;
  assigned_worker_id: string | null;
  payment_status: string | null;
  commission_amount: number;
  worker_payout_amount: number;
  tip_amount?: number;
  is_scheduled?: boolean;
  scheduled_for?: string | null;
  worker_confirmed_readiness?: boolean;
  is_round_trip?: boolean;
  return_otp_required?: boolean;
  return_otp_verified_at?: string | null;
  bids_close_at?: string | null;
  worker_completed_at: string | null;
  customer_confirmed_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  confirmed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  customer: UserBrief | null;
  worker: UserBrief | null;
  requirements: TaskRequirement[];
  my_offer_status?: string | null;
  start_otp_required?: boolean;
  completion_otp_required?: boolean;
  // Handshake codes are only present in the task owner's payload.
  start_otp_display?: string | null;
  completion_otp_display?: string | null;
  start_otp_locked?: boolean;
  completion_otp_locked?: boolean;
  return_otp_display?: string | null;
  return_otp_locked?: boolean;
  status_history?: StatusHistoryEntry[];
  execution_proofs?: TaskExecutionProof[];
  expenses?: TaskExpense[];
  expense_totals?: ExpenseTotals | null;
}

export interface StatusHistoryEntry {
  from_status: string | null;
  to_status: string;
  note: string | null;
  changed_by_role: string | null;
  created_at: string | null;
}

export interface ParsedTaskDraft {
  task_type: TaskType;
  title: string;
  description: string;
  location: string | null;
  latitude: number | null;
  longitude: number | null;
  scheduled_date: string | null;
  scheduled_time: string | null;
  time_of_day: string | null;
  budget: number | null;
  currency: string;
  urgency: Urgency;
  required_skills: string[];
  estimated_duration_minutes: number;
  special_requirements: string[];
  confidence: number;
  provider: string;
  missing_fields: string[];
  clarification_questions: string[];
}

export interface MatchBreakdown {
  distance: number;
  skill_match: number;
  availability: number;
  rating: number;
  reliability: number;
  workload: number;
  final_score: number;
  distance_km: number;
}

export interface Worker {
  id: string;
  full_name: string;
  avatar_url: string | null;
  city: string | null;
  area: string | null;
  bio: string | null;
  experience_years: number;
  languages: string;
  is_online: boolean;
  is_verified: boolean;
  rating_average: number;
  rating_count: number;
  completed_tasks_count: number;
  tier?: WorkerTier;
  skills: string[];
  working_radius_km?: number;
  max_concurrent_tasks?: number;
  cancelled_tasks_count?: number;
  total_earnings?: number;
  verification_status?: string;
  commission_rate?: number;
  upi_id?: string | null;
  queued_task_id?: string | null;
  wrapping_up_soon?: boolean;
  missed_offers?: number;
  availability?: AvailabilityEntry[];
}

export interface AvailabilityEntry {
  day_of_week: number;
  start_time: string;
  end_time: string;
  is_available: boolean;
}

export interface MatchResult {
  worker: Worker;
  breakdown: MatchBreakdown;
}

export interface Offer {
  id: string;
  task_id: string;
  status: string;
  match_score: number;
  expires_at: string | null;
  created_at: string;
  preferred?: boolean;
  chained?: boolean;
  chain_task_id?: string | null;
  badge?: string | null;
  estimated_earnings?: number;
}

export interface OfferWithTask {
  offer: Offer;
  task: Task;
}

export interface EarningsSummary {
  total_earnings: number;
  today_earnings: number;
  week_earnings: number;
  month_earnings: number;
  completed_tasks: number;
  pending_clearance: number;
  currency: string;
}

export interface Wallet {
  id: string;
  balance: number;
  currency: string;
  total_earned: number;
  total_spent: number;
}

export interface Transaction {
  id: string;
  type: string;
  amount: number;
  balance_after: number;
  currency: string;
  reference_type: string | null;
  reference_id: string | null;
  description: string;
  created_at: string;
}

export interface SavedLocation {
  id: string;
  label: string;
  address: string;
  area: string | null;
  city: string | null;
  latitude: number;
  longitude: number;
  is_default: boolean;
  created_at: string;
}

export interface WorkerDocument {
  id: string;
  document_type: string;
  file_name: string;
  mime_type: string;
  file_size: number;
  status: string;
  rejection_reason: string | null;
  created_at: string;
}

export interface Notification {
  id: string;
  type: string;
  title: string;
  body: string;
  data: Record<string, unknown>;
  link: string | null;
  is_read: boolean;
  created_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  body: string;
  is_read: boolean;
  created_at: string;
}

export interface Conversation {
  id: string;
  task_id: string | null;
  task_title: string | null;
  counterpart_id: string | null;
  counterpart_name: string | null;
  counterpart_avatar: string | null;
  last_message_at: string | null;
  unread_count: number;
  chat_open: boolean;
  closes_at: string | null;
  closed_at: string | null;
}

export interface ConversationOpen {
  id: string;
  task_id: string | null;
  chat_open: boolean;
  closes_at: string | null;
}

export interface ChatSocketMessage {
  conversation_id: string;
  task_id: string | null;
  message_id: string;
  sender_id: string;
  sender_name: string;
  body: string;
  created_at: string | null;
}

export type ExpenseCategory = "PARKING" | "GOVT_FEE" | "PURCHASE" | "PRINTING" | "OTHER";
export type ExpenseStatus = "PENDING_APPROVAL" | "APPROVED" | "REJECTED" | "REIMBURSED";

export interface TaskExpense {
  id: string;
  task_id: string;
  worker_id: string;
  amount: number;
  category: ExpenseCategory;
  description: string;
  status: ExpenseStatus;
  receipt_available: boolean;
  receipt_url: string | null;
  decided_by_id: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string | null;
}

export interface ExpenseTotals {
  count: number;
  pending_count: number;
  pending_total: number;
  approved_total: number;
  rejected_total: number;
  reimbursed_total: number;
  worker_reimbursement_total: number;
}

export interface TaskExecutionProof {
  id: string;
  task_id: string;
  worker_id: string;
  captured_at: string | null;
  latitude: number | null;
  longitude: number | null;
  location_source: string | null;
  created_at: string | null;
  file_url: string;
}

export interface ShareLink {
  token: string;
  path: string;
  url: string;
  expires_at: string | null;
}

export interface FareEstimate {
  currency: string;
  minimum_fare: number;
  recommended_fare: number;
  breakdown: {
    base_fare: number;
    distance_km: number;
    distance_charge: number;
    return_distance_km?: number;
    return_charge?: number;
    wait_minutes: number;
    wait_charge: number;
    subtotal: number;
    urgency: string;
    urgency_multiplier: number;
    urgency_surcharge: number;
    minimum_fare: number;
    recommended_fare: number;
  };
}

export interface FareWarning {
  code: "BELOW_MINIMUM_FLOOR" | "BELOW_RECOMMENDED";
  your_budget: number;
  message: string;
}

export interface SosAlert {
  id: string;
  task_id: string;
  status: string;
  raised_by_id: string;
  raised_by_role: string;
  previous_status: string | null;
  latitude: number | null;
  longitude: number | null;
  message: string | null;
  location_history: Array<Record<string, unknown>>;
  created_at: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface PublicTrackingSnapshot {
  status: string;
  tracking_active: boolean;
  destination: {
    latitude: number | null;
    longitude: number | null;
    area_name: string | null;
    city: string | null;
  };
  route: { coordinates: [number, number][]; distance_km: number; duration_min: number } | null;
  latest: {
    latitude: number;
    longitude: number;
    heading: number;
    speed_kmph: number | null;
    remaining_km: number;
    eta_minutes: number;
    recorded_at: string;
  } | null;
  eta_minutes: number | null;
  remaining_km: number | null;
  worker: {
    full_name: string | null;
    avatar_url: string | null;
    rating_average: number;
    rating_count: number;
    is_verified: boolean;
  } | null;
  shared_until: string | null;
}

export interface Rating {
  id: string;
  task_id: string;
  rater_id: string;
  direction: string;
  score: number;
  comment: string | null;
  author_name?: string;
  created_at: string;
}

export interface Review {
  id: string;
  task_id: string;
  author_id: string;
  target_user_id: string;
  rating_score: number;
  body: string;
  created_at: string;
  author_name?: string | null;
}

export interface Dispute {
  id: string;
  task_id: string;
  raised_by_id: string;
  against_id: string | null;
  reason: string;
  description: string;
  status: string;
  resolution_note: string | null;
  resolved_at: string | null;
  created_at: string;
}

export interface Payment {
  id: string;
  task_id: string;
  provider: string;
  amount: number;
  currency: string;
  commission_amount: number;
  worker_payout_amount: number;
  status: string;
  purpose?: string;
  created_at: string;
  captured_at: string | null;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface DashboardMetrics {
  total_users: number;
  total_customers: number;
  total_workers: number;
  active_workers: number;
  verified_workers: number;
  total_tasks: number;
  active_tasks: number;
  completed_tasks: number;
  cancelled_tasks: number;
  disputed_tasks: number;
  completion_rate: number;
  cancellation_rate: number;
  total_revenue: number;
  platform_commission: number;
  worker_payouts: number;
  average_task_value: number;
  average_rating: number;
  open_disputes: number;
}

export interface AdminUserRow {
  id: string;
  full_name: string;
  email: string;
  phone: string | null;
  role: string;
  city: string | null;
  is_active: boolean;
  is_email_verified: boolean;
  created_at: string;
  last_login_at: string | null;
  worker?: {
    is_verified: boolean;
    verification_status: string;
    is_online: boolean;
    rating_average: number;
    total_earnings: number;
  } | null;
}

export interface AdminTaskRow extends Task {}

export interface AuditLog {
  id: string;
  user_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  ip_address: string | null;
  created_at: string;
}

export interface PlatformSetting {
  key: string;
  value: string | number | boolean;
  description: string | null;
}

export interface TrackingUpdate {
  task_id: string;
  status: string;
  latitude: number;
  longitude: number;
  heading: number;
  speed_kmph: number | null;
  remaining_km: number;
  eta_minutes: number;
  recorded_at: string;
}

export interface TrackingSnapshot {
  task_id: string;
  status: string;
  tracking_active: boolean;
  destination: { latitude: number; longitude: number };
  route: { coordinates: [number, number][]; distance_km: number; duration_min: number } | null;
  latest: TrackingUpdate | null;
  eta_minutes: number | null;
  remaining_km: number | null;
  worker: { id: string | null; full_name: string | null; avatar_url: string | null };
}

// ---------------------------------------------------------------------------
// Phase 4 — commercial marketplace
// ---------------------------------------------------------------------------

export type BidStatus = "PENDING" | "ACCEPTED" | "DECLINED" | "EXPIRED" | "WITHDRAWN";

export interface TaskBid {
  id: string;
  task_id: string;
  worker_id: string;
  proposed_amount: number;
  note: string | null;
  estimated_arrival_minutes: number;
  status: BidStatus | string;
  expires_at: string | null;
  responded_at: string | null;
  created_at: string | null;
  worker_name: string | null;
  worker_avatar: string | null;
  worker_rating: number;
  worker_rating_count: number;
  worker_completed_tasks: number;
  worker_tier: WorkerTier | null;
  distance_km: number | null;
}

export interface BidWithTask {
  bid: TaskBid;
  task: Task;
}

export interface TipResult {
  tip: {
    task_id: string;
    amount: number;
    status: string;
    settled: boolean;
  };
  payment: {
    required: boolean;
    key_id?: string;
    order_id?: string;
    amount?: number;
    currency?: string;
    name?: string;
    description?: string;
    prefill?: { name?: string; email?: string; contact?: string };
  } | null;
}

export interface TierRule {
  min_tasks: number;
  min_rating: number;
  max_cancel_rate: number;
  commission_rate: number;
}

export interface TierStats {
  completed_30d: number;
  cancelled_30d: number;
  rating: number;
  rating_count_30d: number;
  cancellation_rate: number;
}

export interface WorkerQuest {
  id: string;
  title: string;
  description: string;
  target_tasks_count: number;
  bonus_amount: number;
  valid_date: string;
  completed_count: number;
  is_claimed: boolean;
  progress_percent: number;
}

export interface WorkerTierOverview {
  tier: WorkerTier;
  commission_rate: number;
  stats: TierStats;
  rule: TierRule;
  next_tier: WorkerTier | null;
  next_tier_rule: TierRule | null;
  quests: WorkerQuest[];
}

export interface PayoutRequest {
  id: string;
  amount: number;
  upi_id: string;
  reference_utr: string;
  status: string;
  failure_reason: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface WithdrawResult {
  payout: PayoutRequest;
  wallet: { balance: number; currency: string; total_earned: number };
}

export type StatementCategory =
  | "base_earnings"
  | "overtime_earnings"
  | "reimbursed_expenses"
  | "tips"
  | "quest_bonuses"
  | "withdrawals"
  | "other_credits";

export interface StatementEntry {
  id: string;
  type: string;
  category: StatementCategory;
  amount: number;
  currency: string;
  description: string;
  reference_type: string | null;
  reference_id: string | null;
  created_at: string | null;
}

export interface WalletStatement {
  worker_id: string;
  period: { from: string; to: string };
  currency: string;
  categories: Record<StatementCategory, number>;
  platform_fees: number;
  gross_earnings: number;
  net_earnings: number;
  withdrawn: number;
  wallet_balance: number;
  transaction_count: number;
  transactions: StatementEntry[];
}

export type RideCheckType = "ROUTE_DEVIATION" | "UNEXPLAINED_STOP";
export type RideCheckStatus = "OPEN" | "ACKNOWLEDGED" | "ESCALATED" | "RESOLVED";

export interface RideCheckEvent {
  id: string;
  task_id: string;
  worker_id: string;
  type: RideCheckType | string;
  status: RideCheckStatus | string;
  latitude: number | null;
  longitude: number | null;
  deviation_m: number | null;
  stationary_seconds: number | null;
  message: string | null;
  acknowledged_at: string | null;
  acknowledgment_reason: string | null;
  resolved_at: string | null;
  admin_flagged_at: string | null;
  created_at: string | null;
  non_dismissible: boolean;
  task_title?: string | null;
  worker_name?: string | null;
}

export interface RideCheckPayload {
  active: RideCheckEvent | null;
  events: RideCheckEvent[];
}

export type AffinityType = "PREFERRED" | "BLACKLISTED";

export interface WorkerAffinity {
  worker_id: string;
  affinity_type: AffinityType;
  full_name: string | null;
  avatar_url: string | null;
  city: string | null;
  rating_average: number;
  rating_count: number;
  completed_tasks_count: number;
  tier: WorkerTier | null;
  updated_at: string | null;
}

export interface AffinityList {
  preferred: WorkerAffinity[];
  blacklisted: WorkerAffinity[];
}

export interface ScheduledSlot {
  task_id: string;
  title: string;
  task_type: TaskType;
  description: string;
  budget: number;
  currency: string;
  city: string | null;
  area_name: string | null;
  address_text: string | null;
  scheduled_for: string | null;
  estimated_duration_minutes: number;
  is_round_trip: boolean;
  distance_km: number | null;
}

export interface WsEvent {
  event: string;
  data: Record<string, unknown>;
}
