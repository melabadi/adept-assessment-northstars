// TypeScript shapes for the requesthub.v1 contract (see app/contracts/openapi.json and
// RequestHub.Core/Services/Dtos.cs). JSON is camelCase; timestamps are ISO 8601 strings.

export type AuthMode = 'Development' | 'EasyAuth';
export type RequestStatus = 'Submitted' | 'InReview' | 'Approved' | 'Rejected';
export type Priority = 'Low' | 'Normal' | 'High' | 'Urgent';
export type DecisionOutcome = 'Approved' | 'Rejected';
export type DecideBlockedReason = 'not_approver' | 'department' | 'self_approval' | 'terminal';
export type Scope = 'mine' | 'queue' | 'all';
export type Role = 'Requester' | 'Reviewer' | 'Approver' | 'Admin';

export const STATUSES: readonly RequestStatus[] = ['Submitted', 'InReview', 'Approved', 'Rejected'];
export const PRIORITIES: readonly Priority[] = ['Low', 'Normal', 'High', 'Urgent'];
export const ROLES: readonly Role[] = ['Requester', 'Reviewer', 'Approver', 'Admin'];

export interface Meta {
  appName: string;
  appVersion: string;
  buildSha: string;
  environment: string;
  industry: string;
  contractVersion: string;
  triageProvider: string;
  authMode: string;
  defaultLocale: string;
}

export interface Persona {
  id: string;
  displayName: string;
  roles: string[];
  departments: string[];
}

export interface Me {
  id: string;
  displayName: string;
  roles: string[];
  departments: string[];
  homeDepartmentId: string;
}

/** Departments and categories share this localized shape. */
export interface NamedItem {
  id: string;
  nameEn: string;
  nameFr: string;
}

export interface Policy {
  id: string;
  version: string;
  kind: string;
  title: string;
  text: string;
  routeTo: string;
  priority: string | null;
  threshold: number | null;
  ref: string;
}

export interface PersonRef {
  id: string;
  displayName: string;
}

export interface RequestSummary {
  id: string;
  title: string;
  category: string;
  departmentId: string;
  priority: Priority;
  status: RequestStatus;
  requester: PersonRef;
  createdAt: string;
  updatedAt: string;
  hasRecommendation: boolean;
}

export interface PagedResult<T> {
  items: T[];
  page: number;
  pageSize: number;
  totalCount: number;
  totalPages: number;
}

export interface Decision {
  outcome: DecisionOutcome;
  decidedBy: PersonRef;
  comment: string | null;
  decidedAt: string;
}

export interface Comment {
  id: string;
  author: PersonRef;
  body: string;
  createdAt: string;
}

export interface Attachment {
  id: string;
  fileName: string;
  contentType: string;
  sizeBytes: number;
  sha256: string;
  uploadedBy: PersonRef;
  uploadedAt: string;
  downloadUrl: string;
}

export interface PolicyRef {
  policyId: string;
  version: string;
}

export interface Recommendation {
  id: string;
  provider: string;
  isSample: boolean;
  suggestedDepartmentId: string;
  suggestedPriority: Priority;
  rationale: string;
  policyRefs: PolicyRef[];
  confidence: number;
  needsHumanReview: boolean;
  status: string;
  departmentAtRecommendation: string;
  createdBy: PersonRef;
  createdAt: string;
  providerTraceId: string | null;
  confirmedBy: PersonRef | null;
}

export interface Permissions {
  canComment: boolean;
  canUpload: boolean;
  canTriage: boolean;
  canRoute: boolean;
  canConfirmRecommendation: boolean;
  canDecide: boolean;
  decideBlockedReason: DecideBlockedReason | null;
}

export interface RequestDetail {
  id: string;
  title: string;
  description: string;
  category: string;
  departmentId: string;
  priority: Priority;
  status: RequestStatus;
  requester: PersonRef;
  createdAt: string;
  updatedAt: string;
  version: string;
  decision: Decision | null;
  latestRecommendation: Recommendation | null;
  comments: Comment[];
  attachments: Attachment[];
  permissions: Permissions;
}

export interface AuditEvent {
  id: number;
  action: string;
  actor: PersonRef;
  occurredAt: string;
  details: Record<string, unknown> | null;
  correlationId: string | null;
}

export interface CreateRequestInput {
  title: string;
  description: string;
  category: string;
  departmentId: string;
  priority: Priority;
}

export interface ListQuery {
  scope: Scope;
  status?: string;
  department?: string;
  priority?: string;
  q?: string;
  page?: number;
  pageSize?: number;
}
