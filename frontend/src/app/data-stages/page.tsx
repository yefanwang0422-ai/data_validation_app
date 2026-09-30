"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Alert from "@mui/material/Alert";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import TextField from "@mui/material/TextField";
import CircularProgress from "@mui/material/CircularProgress";
import Table from "@mui/material/Table";
import TableHead from "@mui/material/TableHead";
import TableBody from "@mui/material/TableBody";
import TableRow from "@mui/material/TableRow";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import Paper from "@mui/material/Paper";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import Divider from "@mui/material/Divider";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import StorageIcon from "@mui/icons-material/Storage";
import AutoFixHighIcon from "@mui/icons-material/AutoFixHigh";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import { DATASETS, api } from "@/lib/api";

// ---- Types ----
interface LayerInfo {
  available: boolean;
  row_count?: number;
  column_count?: number;
  columns?: string[];
  sample?: any[];
  error?: string;
  note?: string;
  grain_report?: any;
  transformations_count?: number;
  outlier_fields?: string[];
  missing_value_summary?: Record<string, number>;
  row_status_counts?: { valid: number; needs_review: number; invalid: number };
  scope_included_count?: number | null;
  scope_excluded_count?: number | null;
}

interface CleanupRow {
  id: string;
  type: string;
  column: string;
  params: string; // human-readable params summary
  rawInstruction: any; // actual instruction dict
}

const INSTRUCTION_TYPES = [
  { value: "rename_column", label: "Rename Column" },
  { value: "remap_values", label: "Remap Values" },
  { value: "mark_as_null", label: "Mark as Null" },
  { value: "exclude_column", label: "Exclude Column" },
  { value: "define_allowed_values", label: "Define Allowed Values" },
  { value: "impute_missing", label: "Impute Missing" },
  { value: "derive_field", label: "Derive New Field" },
  { value: "custom_filter", label: "Custom Filter/Flag" },
  { value: "ai_enrich", label: "AI Geo Enrichment" },
  { value: "standardize_categoricals", label: "Standardize Categoricals" },
];

const LAYER_COLORS = {
  bronze: { bg: "#FEF3E2", border: "#D97706", label: "#92400E" },
  silver: { bg: "#EFF6FF", border: "#3B82F6", label: "#1E40AF" },
  gold: { bg: "#F0FDF4", border: "#16A34A", label: "#14532D" },
};

// ---- Helpers ----
function instructionToParams(instr: any): string {
  switch (instr.type) {
    case "rename_column": return `→ ${instr.new_name}`;
    case "remap_values": return Object.entries(instr.value_map || {}).map(([k, v]) => `"${k}" → "${v}"`).join(", ");
    case "mark_as_null": return `Values: ${(instr.values || []).join(", ")}`;
    case "exclude_column": return instr.reason || "Excluded";
    case "define_allowed_values": return `Allowed: ${(instr.allowed_values || []).join(", ")}`;
    case "impute_missing": return `Strategy: ${instr.strategy}${instr.value !== undefined ? ` = ${instr.value}` : ""}`;
    case "derive_field": return `New: ${instr.new_column} = ${instr.expression}`;
    case "custom_filter": return `${instr.condition} → flag: ${instr.flag_column}`;
    case "ai_enrich": return `Fill fields: ${(instr.fields || ["city","state","postal_code","latitude","longitude"]).join(", ")}`;
    case "standardize_categoricals": return instr.columns ? `Columns: ${(instr.columns || []).join(", ")}` : "All categorical columns";
    default: return JSON.stringify(instr);
  }
}

// ---- Main Page ----
export default function DataStagesPage() {
  const { projectId, runId } = useProject();
  const [dataset, setDataset] = React.useState<string>(DATASETS[0]);
  const [stages, setStages] = React.useState<{ layers: { bronze: LayerInfo; silver: LayerInfo; gold: LayerInfo } } | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Cleanup rows (table)
  const [cleanupRows, setCleanupRows] = React.useState<CleanupRow[]>([]);
  const [applyLoading, setApplyLoading] = React.useState(false);
  const [applyResult, setApplyResult] = React.useState<any>(null);
  const [applyError, setApplyError] = React.useState<string | null>(null);

  // NL input
  const [nlText, setNlText] = React.useState("");
  const [nlLoading, setNlLoading] = React.useState(false);
  const [nlError, setNlError] = React.useState<string | null>(null);

  async function loadStages() {
    if (!runId) return;
    setLoading(true);
    setError(null);
    setStages(null);
    try {
      const { data } = await api.get(`/data-stages/${projectId}/${dataset}/${runId}`);
      setStages(data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => { if (runId) loadStages(); }, [projectId, runId, dataset]);

  // Parse natural language → add rows to table
  async function handleParseNL() {
    if (!nlText.trim()) return;
    setNlLoading(true);
    setNlError(null);
    try {
      const { data } = await api.post("/silver-cleanup/parse-nl", { text: nlText });
      const newRows: CleanupRow[] = (data.instructions || []).map((instr: any) => ({
        id: Math.random().toString(36).slice(2),
        type: instr.type,
        column: instr.column || instr.new_column || "—",
        params: instructionToParams(instr),
        rawInstruction: instr,
      }));
      setCleanupRows((prev) => [...prev, ...newRows]);
      setNlText("");
      if (newRows.length === 0) {
        setNlError("AI could not parse any instructions from that text. Try being more specific.");
      }
    } catch (e: any) {
      setNlError(e?.response?.data?.detail || e.message || "Parse failed");
    } finally {
      setNlLoading(false);
    }
  }

  function removeRow(id: string) {
    setCleanupRows((prev) => prev.filter((r) => r.id !== id));
  }

  async function handleApply() {
    if (!runId || cleanupRows.length === 0) return;
    setApplyLoading(true);
    setApplyError(null);
    setApplyResult(null);
    try {
      const instructions = cleanupRows.map((r) => r.rawInstruction);
      const { data } = await api.post(`/silver-cleanup/${projectId}/${dataset}/${runId}`, {
        project_id: projectId,
        run_id: runId,
        instructions,
        approved_by: "user",
      });
      setApplyResult(data);
      setCleanupRows([]); // Clear table after apply
      await loadStages();
    } catch (e: any) {
      setApplyError(e?.response?.data?.detail || e.message || "Apply failed");
    } finally {
      setApplyLoading(false);
    }
  }

  // ---- Layer Card ----
  const LayerCard = ({ layer, info }: { layer: "bronze" | "silver" | "gold"; info: LayerInfo }) => {
    const colors = LAYER_COLORS[layer];
    return (
      <Card sx={{ border: `2px solid ${colors.border}`, bgcolor: colors.bg, height: "100%" }}>
        <CardContent>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1.5 }}>
            <StorageIcon sx={{ color: colors.border }} />
            <Typography variant="subtitle1" sx={{ fontWeight: 700, color: colors.label, flexGrow: 1 }}>
              {layer.charAt(0).toUpperCase() + layer.slice(1)} Layer
            </Typography>
            <Chip label={info.available ? "Available" : "Not Ready"} color={info.available ? "success" : "default"} size="small" />
          </Box>

          {!info.available ? (
            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: "italic" }}>{info.note || info.error || "No data"}</Typography>
          ) : (
            <>
              {/* Stats row */}
              <Box sx={{ display: "flex", gap: 3, mb: 1.5 }}>
                <Box sx={{ textAlign: "center" }}>
                  <Typography variant="h5" sx={{ fontWeight: 700, color: colors.label }}>{info.row_count?.toLocaleString()}</Typography>
                  <Typography variant="caption" color="text.secondary">Rows</Typography>
                </Box>
                <Box sx={{ textAlign: "center" }}>
                  <Typography variant="h5" sx={{ fontWeight: 700, color: colors.label }}>{info.column_count}</Typography>
                  <Typography variant="caption" color="text.secondary">Columns</Typography>
                </Box>
              </Box>

              {/* Silver chips */}
              {layer === "silver" && (
                <Box sx={{ mb: 1, display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                  {info.grain_report && (
                    <Chip
                      label={info.grain_report.grain_is_valid ? "Grain Valid" : "Grain Violation"}
                      color={info.grain_report.grain_is_valid ? "success" : "error"}
                      size="small" icon={<CheckCircleIcon />}
                    />
                  )}
                  {(info.outlier_fields || []).length > 0 && (
                    <Chip label={`${info.outlier_fields!.length} Outlier Fields`} color="warning" size="small" />
                  )}
                  {info.transformations_count ? (
                    <Chip label={`${info.transformations_count} Transformations`} color="info" size="small" />
                  ) : null}
                  {info.scope_excluded_count !== undefined && info.scope_excluded_count !== null && (
                    <>
                      <Chip
                        label={`Scope: ${info.scope_included_count?.toLocaleString()} in-scope`}
                        color="success"
                        size="small"
                        variant="outlined"
                      />
                      <Chip
                        label={`${info.scope_excluded_count?.toLocaleString()} excluded`}
                        color={info.scope_excluded_count > 0 ? "warning" : "default"}
                        size="small"
                        variant="outlined"
                      />
                    </>
                  )}
                </Box>
              )}
              {layer === "silver" && info.scope_excluded_count !== undefined && info.scope_excluded_count !== null && (
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                  Scope Filter applied here — master exclusions cascade to related transactional rows.
                </Typography>
              )}

              {/* Gold status */}
              {layer === "gold" && info.row_status_counts && (
                <Box sx={{ display: "flex", gap: 0.5, mb: 1, flexWrap: "wrap" }}>
                  <Chip label={`Valid: ${info.row_status_counts.valid?.toLocaleString()}`} color="success" size="small" />
                  <Chip label={`Review: ${info.row_status_counts.needs_review?.toLocaleString()}`} color="warning" size="small" />
                  <Chip label={`Invalid: ${info.row_status_counts.invalid?.toLocaleString()}`} color="error" size="small" />
                </Box>
              )}

              {/* Missing values (Silver) */}
              {layer === "silver" && info.missing_value_summary && Object.keys(info.missing_value_summary).length > 0 && (
                <Accordion disableGutters sx={{ bgcolor: "transparent", boxShadow: "none", mb: 0.5 }}>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ p: 0, minHeight: 28 }}>
                    <Typography variant="caption" color="warning.main">
                      Missing values in {Object.keys(info.missing_value_summary).length} columns
                    </Typography>
                  </AccordionSummary>
                  <AccordionDetails sx={{ p: 0 }}>
                    <TableContainer>
                      <Table size="small">
                        <TableHead>
                          <TableRow sx={{ bgcolor: "#F9FAFB" }}>
                            <TableCell sx={{ fontSize: 11, py: 0.5 }}>Column</TableCell>
                            <TableCell sx={{ fontSize: 11, py: 0.5 }}>% Missing</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {Object.entries(info.missing_value_summary).map(([col, pct]) => (
                            <TableRow key={col}>
                              <TableCell sx={{ fontFamily: "monospace", fontSize: 11, py: 0.5 }}>{col}</TableCell>
                              <TableCell sx={{ py: 0.5 }}>
                                <Chip label={`${pct}%`} size="small"
                                  color={pct > 30 ? "error" : pct > 5 ? "warning" : "default"} />
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </AccordionDetails>
                </Accordion>
              )}

              {/* Sample rows */}
              {(info.sample || []).length > 0 && (
                <Accordion disableGutters sx={{ bgcolor: "transparent", boxShadow: "none" }}>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ p: 0, minHeight: 28 }}>
                    <Typography variant="caption" color="text.secondary">Show sample rows (3)</Typography>
                  </AccordionSummary>
                  <AccordionDetails sx={{ p: 0 }}>
                    <TableContainer sx={{ maxHeight: 180 }}>
                      <Table size="small" stickyHeader>
                        <TableHead>
                          <TableRow>
                            {Object.keys(info.sample![0] || {}).slice(0, 6).map((col) => (
                              <TableCell key={col} sx={{ fontSize: 10, py: 0.5, fontFamily: "monospace", bgcolor: "#F3F4F6" }}>{col}</TableCell>
                            ))}
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {info.sample!.slice(0, 3).map((row, i) => (
                            <TableRow key={i}>
                              {Object.values(row).slice(0, 6).map((val: any, j) => (
                                <TableCell key={j} sx={{ fontSize: 10, py: 0.5, maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                  {val === null || val === undefined ? "—" : String(val)}
                                </TableCell>
                              ))}
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </AccordionDetails>
                </Accordion>
              )}
            </>
          )}
        </CardContent>
      </Card>
    );
  };

  return (
    <Box>
      <PageHeader
        title="Data Stage Viewer"
        subtitle="Inspect Bronze, Silver, and Gold layers side-by-side. Apply LLM-assisted cleanup to Silver using natural language or structured instructions."
        actions={
          <Select size="small" value={dataset} onChange={(e) => setDataset(e.target.value)}>
            {DATASETS.map((d) => (
              <MenuItem key={d} value={d}>{d.replace(/_/g, " ")}</MenuItem>
            ))}
          </Select>
        }
      />

      {!runId && <Alert severity="info" sx={{ mb: 3 }}>Select a run from the sidebar or Run History to view data stages.</Alert>}
      {loading && <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}><CircularProgress /></Box>}
      {error && <Alert severity="error" sx={{ mb: 3 }}>{error}</Alert>}

      {stages && (
        <>
          {/* Layer cards */}
          <Grid container spacing={2} sx={{ mb: 4 }}>
            {(["bronze", "silver", "gold"] as const).map((layer) => (
              <Grid item xs={12} md={4} key={layer}>
                <LayerCard layer={layer} info={stages.layers[layer]} />
              </Grid>
            ))}
          </Grid>

          {/* Silver Cleanup Section */}
          {stages.layers.silver.available && (
            <Card>
              <CardContent>
                <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
                  <AutoFixHighIcon sx={{ color: "primary.main" }} />
                  <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>LLM-Assisted Silver Cleanup</Typography>
                  <Chip label="Silver layer only — Bronze never modified" size="small" color="info" variant="outlined" sx={{ ml: "auto" }} />
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Describe cleanup actions in plain English or build a table of instructions. All changes are logged with a full audit trail.
                </Typography>

                {/* NL input */}
                <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: "#F8FAFF" }}>
                  <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1, mb: 1 }}>
                    <SmartToyIcon sx={{ color: "primary.main", mt: 0.5 }} />
                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>Natural Language Input</Typography>
                  </Box>
                  <TextField
                    fullWidth
                    multiline
                    minRows={2}
                    placeholder='e.g. "rename ShipDate to shipment_date", "treat N/A and - as missing in city column", "map TL and LTL to Truck in shipment_mode"'
                    value={nlText}
                    onChange={(e) => setNlText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey) handleParseNL(); }}
                    sx={{ mb: 1 }}
                  />
                  {nlError && <Alert severity="warning" sx={{ mb: 1 }}>{nlError}</Alert>}
                  <Button
                    variant="outlined"
                    startIcon={nlLoading ? <CircularProgress size={14} color="inherit" /> : <SmartToyIcon />}
                    onClick={handleParseNL}
                    disabled={nlLoading || !nlText.trim()}
                    size="small"
                  >
                    {nlLoading ? "Parsing with AI..." : "Parse & Add to Instructions Table"}
                  </Button>
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 2 }}>
                    Or Ctrl+Enter
                  </Typography>
                </Paper>

                {/* Instructions table */}
                <Box sx={{ mb: 2 }}>
                  <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                      Cleanup Instructions ({cleanupRows.length})
                    </Typography>
                    {cleanupRows.length > 0 && (
                      <Button size="small" color="error" onClick={() => setCleanupRows([])}>Clear All</Button>
                    )}
                  </Box>

                  {cleanupRows.length === 0 ? (
                    <Paper variant="outlined" sx={{ p: 3, textAlign: "center", bgcolor: "#F9FAFB" }}>
                      <Typography color="text.secondary" variant="body2">
                        No instructions yet. Describe what you want above, or the AI will parse your text into structured instructions.
                      </Typography>
                    </Paper>
                  ) : (
                    <TableContainer component={Paper} variant="outlined">
                      <Table size="small">
                        <TableHead>
                          <TableRow sx={{ bgcolor: "#EEF3FC" }}>
                            <TableCell sx={{ fontWeight: 600 }}>#</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Instruction Type</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Column</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Parameters</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Remove</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {cleanupRows.map((row, i) => (
                            <TableRow key={row.id} sx={{ "&:hover": { bgcolor: "#F9FAFB" } }}>
                              <TableCell sx={{ color: "text.secondary", fontSize: 12 }}>{i + 1}</TableCell>
                              <TableCell>
                                <Chip
                                  label={INSTRUCTION_TYPES.find((t) => t.value === row.type)?.label || row.type}
                                  size="small" color="primary" variant="outlined"
                                />
                              </TableCell>
                              <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{row.column}</TableCell>
                              <TableCell sx={{ fontSize: 12, maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" }}>{row.params}</TableCell>
                              <TableCell>
                                <IconButton size="small" color="error" onClick={() => removeRow(row.id)}>
                                  <DeleteIcon fontSize="small" />
                                </IconButton>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )}
                </Box>

                {/* Apply button */}
                {cleanupRows.length > 0 && (
                  <Button
                    variant="contained"
                    startIcon={applyLoading ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                    onClick={handleApply}
                    disabled={applyLoading}
                    sx={{ mb: applyResult ? 2 : 0 }}
                  >
                    {applyLoading ? "Applying to Silver..." : `Apply ${cleanupRows.length} Instruction${cleanupRows.length > 1 ? "s" : ""} to Silver`}
                  </Button>
                )}

                {applyError && <Alert severity="error" sx={{ mt: 2 }}>{applyError}</Alert>}

                {/* Decision log table */}
                {applyResult && (
                  <Box sx={{ mt: 2 }}>
                    <Alert severity="success" sx={{ mb: 2 }}>
                      <strong>{applyResult.instructions_processed} instructions applied</strong> to Silver layer.
                      Full audit log saved. Re-run validation (Phase 3) to promote to Gold.
                    </Alert>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>Decision Log</Typography>
                    <TableContainer component={Paper} variant="outlined">
                      <Table size="small">
                        <TableHead>
                          <TableRow sx={{ bgcolor: "#EEF3FC" }}>
                            <TableCell sx={{ fontWeight: 600 }}>Type</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Column</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Status</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Message</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {(applyResult.decisions || []).map((d: any, i: number) => (
                            <TableRow key={i} sx={{ bgcolor: d.status === "error" ? "#FEF2F2" : d.status === "skipped" ? "#FFFBEB" : undefined }}>
                              <TableCell>
                                <Chip label={d.type} size="small" color="primary" variant="outlined" />
                              </TableCell>
                              <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{d.column || "—"}</TableCell>
                              <TableCell>
                                <Chip
                                  label={d.status}
                                  size="small"
                                  color={d.status === "applied" ? "success" : d.status === "error" ? "error" : "warning"}
                                />
                              </TableCell>
                              <TableCell sx={{ fontSize: 12 }}>
                                {d.message}
                                {d.modeling_integrity_warning && (
                                  <Typography variant="caption" color="warning.main" display="block">
                                    ⚠ {d.modeling_integrity_warning}
                                  </Typography>
                                )}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </Box>
                )}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </Box>
  );
}
