import axios from "axios";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: API_BASE_URL,
});

export interface RunSummary {
  run_id: string;
  project_id: string;
  extraction_source?: string;
  datasets: Record<
    string,
    {
      row_count: number;
      valid: number;
      needs_review: number;
      invalid: number;
      scope_excluded?: number;
      skipped?: boolean;
      reason?: string;
    }
  >;
  skipped_datasets?: string[];
  extraction_errors?: Record<string, string>;
  issue_count: number;
  review_queue_count: number;
  cross_reference_exception_count: number;
}

export interface DatasetQuality {
  dataset: string;
  row_count: number;
  pct_valid: number;
  pct_needs_review: number;
  pct_invalid: number;
  ai_filled_count: number;
}

export const DATASETS = [
  "customer_master",
  "location_master",
  "vendor_master",
  "product_master",
  "production_history",
  "shipment_history",
  "inbound_shipment_history",
  "outbound_shipment_history",
  "shipment_cost",
  "inventory_history",
] as const;

export type Dataset = (typeof DATASETS)[number];

export type StatusFilter = "all" | "validated" | "flagged" | "unresolved";

export async function listRuns(projectId: string): Promise<string[]> {
  const { data } = await api.get(`/runs/${projectId}`);
  return data.runs;
}

export async function getRunSummary(projectId: string, runId: string): Promise<RunSummary> {
  const { data } = await api.get(`/runs/${projectId}/${runId}/summary`);
  return data;
}

export async function runPipeline(projectId: string, useSampleData: boolean | null = null) {
  const { data } = await api.post(`/pipeline/run`, {
    project_id: projectId,
    use_sample_data: useSampleData,
  });
  return data as RunSummary;
}

export async function extractOnly(projectId: string, useSampleData: boolean | null = null) {
  const { data } = await api.post(`/pipeline/extract-only`, {
    project_id: projectId,
    use_sample_data: useSampleData,
  });
  return data as RunSummary;
}

export async function refreshAllMappings(projectId: string, runId: string) {
  const { data } = await api.post(`/pipeline/refresh-all-mappings`, {
    project_id: projectId,
    run_id: runId,
  });
  return data as { status: string; datasets: any[]; errors: Record<string, string> };
}

export async function getCanonicalFields(dataset: string): Promise<string[]> {
  const { data } = await api.get(`/config/canonical-fields/${dataset}`);
  return data.fields;
}

export async function runFromBronze(projectId: string, runId: string) {
  const { data } = await api.post(`/pipeline/run-from-bronze`, {
    project_id: projectId,
    run_id: runId,
  });
  return data as RunSummary;
}

export async function getDatasetQuality(
  projectId: string,
  runId: string
): Promise<Record<string, DatasetQuality>> {
  const { data } = await api.get(`/runs/${projectId}/${runId}/quality`);
  return data;
}

export async function getIssues(projectId: string, runId: string, dataset: string) {
  const { data } = await api.get(`/runs/${projectId}/${runId}/issues/${dataset}`);
  return data as { dataset: string; count: number; records: any[] };
}

export async function getCrossReferenceExceptions(
  projectId: string,
  runId: string,
  dataset: string
) {
  const { data } = await api.get(
    `/runs/${projectId}/${runId}/cross-reference-exceptions/${dataset}`
  );
  return data as { dataset: string; count: number; records: any[] };
}

export async function getReviewQueue(projectId: string, runId: string, dataset: string) {
  const { data } = await api.get(`/runs/${projectId}/${runId}/review-queue/${dataset}`);
  return data as { dataset: string; count: number; records: any[] };
}

export async function submitReviewDecision(
  projectId: string,
  runId: string,
  dataset: string,
  recordIndex: number,
  payload: { decision: string; corrected_value?: string; reviewer?: string; comment?: string }
) {
  const { data } = await api.post(
    `/review/${projectId}/${runId}/${dataset}/${recordIndex}/decision`,
    payload
  );
  return data;
}

export async function getRawVsValidated(
  projectId: string,
  runId: string,
  dataset: string,
  statusFilter: StatusFilter = "all"
) {
  const { data } = await api.get(`/views/${projectId}/${runId}/${dataset}`, {
    params: { status_filter: statusFilter },
  });
  return data as { dataset: string; count: number; records: any[] };
}

export async function getBusinessMetric(
  projectId: string,
  runId: string,
  metricName: string,
  statusFilter: StatusFilter = "all"
) {
  const { data } = await api.get(`/metrics/${projectId}/${runId}/${metricName}`, {
    params: { status_filter: statusFilter },
  });
  return data; // Plotly figure JSON: { data: [...], layout: {...} }
}

export async function listMetrics(): Promise<string[]> {
  const { data } = await api.get(`/metrics`);
  return data.metrics;
}

export async function getMapping(projectId: string, dataset: string) {
  const { data } = await api.get(`/mappings/${projectId}/${dataset}`);
  return data as { dataset: string; entries: any[] };
}

export async function approveMapping(projectId: string, dataset: string, rawColumn: string) {
  const { data } = await api.post(
    `/mappings/${projectId}/${dataset}/${encodeURIComponent(rawColumn)}/approve`
  );
  return data;
}

export async function exportRun(projectId: string, runId: string) {
  const { data } = await api.post(`/export/${projectId}/${runId}`);
  return data as Record<string, string>;
}

export function optilogicExportUrl(projectId: string, runId: string, dataset: string) {
  return `${API_BASE_URL}/export/${projectId}/${runId}/${dataset}/optilogic`;
}

export async function getSqlStatus(): Promise<boolean> {
  const { data } = await api.get(`/config/sql-status`);
  return data.sql_configured;
}

export interface DatasetQueryConfig {
  load_mode: string;
  watermark_column?: string | null;
  query: string;
}

export interface SqlConnectionConfig {
  connection: { server: string; database: string; driver: string };
  datasets: Record<string, DatasetQueryConfig>;
}

export async function getSqlConnectionConfig(): Promise<SqlConnectionConfig> {
  const { data } = await api.get(`/config/sql-connection`);
  return data;
}

export async function getOdbcDrivers(): Promise<string[]> {
  const { data } = await api.get(`/config/odbc-drivers`);
  return data.drivers;
}

export async function testSqlConnection(server: string, database: string, driver: string) {
  const { data } = await api.post(`/config/sql-connection/test`, { server, database, driver });
  return data as { success: boolean; message: string };
}

export async function saveSqlConnectionConfig(
  server: string,
  database: string,
  driver: string,
  queries: Record<string, DatasetQueryConfig>
) {
  const { data } = await api.post(`/config/sql-connection`, { server, database, driver, queries });
  return data as { status: string; sql_configured: boolean };
}

export type DataSourceType = "sql" | "file" | "none";

export interface DataSourceEntry {
  source_type: DataSourceType;
  upload_filename: string | null;
  uploaded_filename: string | null;
}

export async function getDataSources(
  projectId: string
): Promise<Record<string, DataSourceEntry>> {
  const { data } = await api.get(`/data-sources/${projectId}`);
  return data.datasets;
}

export async function setDataSourceType(
  projectId: string,
  dataset: string,
  sourceType: DataSourceType
) {
  const { data } = await api.post(`/data-sources/${projectId}/${dataset}/source-type`, {
    source_type: sourceType,
  });
  return data;
}

export async function uploadDatasetFile(projectId: string, dataset: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post(`/data-sources/${projectId}/${dataset}/upload`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data as { status: string; dataset: string; filename: string; path: string };
}

// ---------------------------------------------------------------------------
// Scope Filters — user-defined business scope rules
// ---------------------------------------------------------------------------

export interface ScopeRule {
  id?: string;
  type: "date_range" | "include_values" | "exclude_values" | "numeric_range";
  field: string;
  description?: string;
  start?: string;
  end?: string;
  values?: string[];
  min?: number;
  max?: number;
}

export async function getAllScopeFilters(projectId: string) {
  const { data } = await api.get(`/scope-filters/${projectId}`);
  return data as { project_id: string; rules: Record<string, ScopeRule[]> };
}

export async function getDatasetScopeFilters(projectId: string, dataset: string) {
  const { data } = await api.get(`/scope-filters/${projectId}/${dataset}`);
  return data as { project_id: string; dataset: string; rules: ScopeRule[] };
}

export async function saveDatasetScopeFilters(projectId: string, dataset: string, rules: ScopeRule[]) {
  const { data } = await api.post(`/scope-filters/${projectId}/${dataset}`, { rules });
  return data as { status: string; dataset: string; rule_count: number };
}

export interface ScopeSummaryEntry {
  total: number;
  included: number;
  excluded: number;
  pct_excluded: number;
  reasons: Record<string, number>;
}

export async function getScopeSummary(projectId: string, runId: string) {
  const { data } = await api.get(`/runs/${projectId}/${runId}/scope-summary`);
  return data as { project_id: string; run_id: string; datasets: Record<string, ScopeSummaryEntry> };
}

export async function getExcludedRecords(projectId: string, runId: string, dataset: string) {
  const { data } = await api.get(`/runs/${projectId}/${runId}/excluded/${dataset}`);
  return data as { dataset: string; count: number; records: any[] };
}

export type FlowMapMetric = "volume" | "count";

export interface FlowMapNode {
  id: string;
  name: string;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  lat: number | null;
  lon: number | null;
}

export interface FlowMapLane {
  origin: string;
  destination: string;
  value: number;
}

export interface FlowMapResponse {
  mode: "inbound" | "outbound";
  nodes: FlowMapNode[];
  lanes: FlowMapLane[];
  metric?: FlowMapMetric;
  top_n?: number;
  note?: string;
}

export async function getInboundFlowMap(
  projectId: string,
  runId: string,
  statusFilter: StatusFilter = "all",
  topN: number = 150,
  metric: FlowMapMetric = "volume"
) {
  const { data } = await api.get(`/flow-maps/${projectId}/${runId}/inbound`, {
    params: { status_filter: statusFilter, top_n: topN, metric },
  });
  return data as FlowMapResponse;
}

export async function getOutboundFlowMap(
  projectId: string,
  runId: string,
  statusFilter: StatusFilter = "all",
  topN: number = 150,
  metric: FlowMapMetric = "volume"
) {
  const { data } = await api.get(`/flow-maps/${projectId}/${runId}/outbound`, {
    params: { status_filter: statusFilter, top_n: topN, metric },
  });
  return data as FlowMapResponse;
}
