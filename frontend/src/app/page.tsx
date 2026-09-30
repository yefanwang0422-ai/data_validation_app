"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import Stepper from "@mui/material/Stepper";
import Step from "@mui/material/Step";
import StepLabel from "@mui/material/StepLabel";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import CloudDownloadIcon from "@mui/icons-material/CloudDownload";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import FilterAltIcon from "@mui/icons-material/FilterAlt";
import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import {
  extractOnly,
  runFromBronze,
  refreshAllMappings,
  approveMapping,
  getCanonicalFields,
  getMapping,
  api,
  RunSummary,
  DATASETS,
} from "@/lib/api";

interface MappingEntry {
  raw_column: string;
  canonical_field: string;
  confidence: number;
  source: string;
  approved: boolean;
}

interface DatasetMappingState {
  entries: MappingEntry[];
  loading: boolean;
}

export default function RunPipelinePage() {
  const { projectId, setRunId, refreshRuns } = useProject();

  // Step tracking: 0=idle, 1=extraction in progress, 2=mapping review, 3=validation in progress, 4=complete
  const [step, setStep] = React.useState(0);
  const [extractedSummary, setExtractedSummary] = React.useState<RunSummary | null>(null);
  const [finalSummary, setFinalSummary] = React.useState<RunSummary | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [mappings, setMappings] = React.useState<Record<string, DatasetMappingState>>({});
  const [refreshingMappings, setRefreshingMappings] = React.useState(false);
  // Per-dataset canonical field lists (fetched from API, scoped to each dataset's schema)
  const [datasetCanonicalFields, setDatasetCanonicalFields] = React.useState<Record<string, string[]>>({});

  // Active datasets extracted in Phase 1
  const activeDatasets = React.useMemo(() => {
    if (!extractedSummary) return [];
    return Object.entries(extractedSummary.datasets)
      .filter(([, v]) => !(v as any).skipped)
      .map(([k]) => k);
  }, [extractedSummary]);

  // Load mappings + canonical field lists for all active datasets after extraction
  React.useEffect(() => {
    if (step !== 2 || !extractedSummary) return;
    const projectIdVal = projectId;
    setMappings({});
    setDatasetCanonicalFields({});
    for (const dataset of activeDatasets) {
      setMappings((prev) => ({ ...prev, [dataset]: { entries: [], loading: true } }));
      // Fetch mapping entries and dataset-specific canonical fields in parallel
      Promise.all([
        getMapping(projectIdVal, dataset),
        getCanonicalFields(dataset),
      ])
        .then(([mappingRes, fieldsRes]) => {
          setMappings((prev) => ({
            ...prev,
            [dataset]: { entries: mappingRes.entries as MappingEntry[], loading: false },
          }));
          setDatasetCanonicalFields((prev) => ({ ...prev, [dataset]: fieldsRes }));
        })
        .catch(() =>
          setMappings((prev) => ({ ...prev, [dataset]: { entries: [], loading: false } }))
        );
    }
  }, [step, extractedSummary, activeDatasets, projectId]);

  // ---- Phase 1: Extract ----
  async function handleExtract() {
    setStep(1);
    setError(null);
    setExtractedSummary(null);
    setFinalSummary(null);
    try {
      const result = await extractOnly(projectId, null);
      setExtractedSummary(result);
      setRunId(result.run_id);
      await refreshRuns();
      setStep(2);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || "Extraction failed");
      setStep(0);
    }
  }

  // ---- Phase 2: Refresh all mappings (for stale/already-extracted runs) ----
  async function handleRefreshAllMappings() {
    if (!extractedSummary) return;
    setRefreshingMappings(true);
    try {
      await refreshAllMappings(projectId, extractedSummary.run_id);
      // Reload all mapping entries after refresh
      setMappings({});
      setDatasetCanonicalFields({});
      for (const dataset of activeDatasets) {
        setMappings((prev) => ({ ...prev, [dataset]: { entries: [], loading: true } }));
        Promise.all([getMapping(projectId, dataset), getCanonicalFields(dataset)])
          .then(([mappingRes, fieldsRes]) => {
            setMappings((prev) => ({
              ...prev,
              [dataset]: { entries: mappingRes.entries as MappingEntry[], loading: false },
            }));
            setDatasetCanonicalFields((prev) => ({ ...prev, [dataset]: fieldsRes }));
          })
          .catch(() => setMappings((prev) => ({ ...prev, [dataset]: { entries: [], loading: false } })));
      }
    } finally {
      setRefreshingMappings(false);
    }
  }

  // ---- Phase 2: Mapping actions ----
  async function handleApproveMapping(dataset: string, rawColumn: string) {
    if (!extractedSummary) return;
    await approveMapping(projectId, dataset, rawColumn);
    const res = await getMapping(projectId, dataset);
    setMappings((prev) => ({
      ...prev,
      [dataset]: { entries: res.entries as MappingEntry[], loading: false },
    }));
  }

  async function handleOverrideCanonical(dataset: string, rowIdx: number, rawColumn: string, newField: string) {
    if (!extractedSummary) return;
    const current = mappings[dataset]?.entries || [];
    const updated = current.map((e, i) =>
      i === rowIdx ? { ...e, canonical_field: newField, source: "manual_override", approved: false } : e
    );
    await api.post(`/mappings/${projectId}/${dataset}/patch`, {
      entries: updated.map(({ ...rest }) => rest),
    });
    await approveMapping(projectId, dataset, rawColumn);
    const res = await getMapping(projectId, dataset);
    setMappings((prev) => ({
      ...prev,
      [dataset]: { entries: res.entries as MappingEntry[], loading: false },
    }));
  }

  // Count pending approvals (only rows that have a canonical field assigned but not yet approved)
  // Blank-canonical-field rows are intentionally excluded — they don't need approval.
  const pendingCount = React.useMemo(() => {
    let count = 0;
    for (const ds of activeDatasets) {
      const entries = mappings[ds]?.entries || [];
      count += entries.filter((e) => e.canonical_field && !e.approved).length;
    }
    return count;
  }, [mappings, activeDatasets]);

  // ---- Phase 3: Run Validation ----
  async function handleRunValidation() {
    if (!extractedSummary) return;
    setStep(3);
    setError(null);
    try {
      const result = await runFromBronze(projectId, extractedSummary.run_id);
      setFinalSummary(result);
      await refreshRuns();
      setStep(4);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || "Validation failed");
      setStep(2);
    }
  }

  return (
    <Box>
      <PageHeader
        title="Run Pipeline"
        subtitle="Bronze (extract) → Silver (canonical mapping) → Scope Filter (business scope + cascade) → Profiling → Validation → AI Enrichment → Gold"
      />

      <Stepper
        activeStep={Math.min(step === 4 ? 3 : step, 3)}
        sx={{ mb: 4, "& .MuiStepLabel-label": { fontWeight: 600 } }}
      >
        <Step>
          <StepLabel icon={<CloudDownloadIcon />}>Extract to Bronze</StepLabel>
        </Step>
        <Step>
          <StepLabel icon={<AccountTreeIcon />}>Review Column Mapping</StepLabel>
        </Step>
        <Step>
          <StepLabel icon={<FactCheckIcon />}>Scope Filter → Validate & Profile</StepLabel>
        </Step>
      </Stepper>

      {error && <Alert severity="error" sx={{ mb: 3 }}>{error}</Alert>}

      {/* ---- STEP 1: Extract ---- */}
      {(step === 0 || step === 1) && (
        <Card>
          <CardContent>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
              Step 1 — Extract Data
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Pull data from your configured SQL / uploaded file sources into the Bronze staging layer,
              then automatically suggest canonical column mappings for your review in Step 2.
            </Typography>
            <Button
              variant="contained"
              size="large"
              startIcon={step === 1 ? <CircularProgress size={18} color="inherit" /> : <CloudDownloadIcon />}
              onClick={handleExtract}
              disabled={step === 1}
            >
              {step === 1 ? "Extracting Data..." : "Extract Data Now"}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* ---- STEP 2: Mapping Review ---- */}
      {step >= 2 && step <= 3 && extractedSummary && (
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                  Step 2 — Review Column Mapping
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Review AI-suggested mappings from your raw file columns to canonical field names.
                  Override any mapping using the dropdown, then approve. Unapproved mappings are still included
                  in Silver as <code>raw__column_name</code>.
                </Typography>
              </Box>
              <Box>
                <Button
                  variant="text"
                  size="small"
                  onClick={handleRefreshAllMappings}
                  disabled={refreshingMappings}
                  sx={{ mr: 1, color: "text.secondary" }}
                >
                  {refreshingMappings ? "Refreshing..." : "↻ Refresh Mappings"}
                </Button>
                {pendingCount > 0 && (
                  <Chip label={`${pendingCount} awaiting approval`} color="warning" sx={{ mr: 2 }} />
                )}
                <Button
                  variant="contained"
                  color="primary"
                  startIcon={step === 3 ? <CircularProgress size={18} color="inherit" /> : <FactCheckIcon />}
                  onClick={handleRunValidation}
                  disabled={step === 3}
                >
                  {step === 3 ? "Validating..." : "Confirm Mappings & Run Validation"}
                </Button>
              </Box>
            </Box>

            <Alert
              severity="info"
              icon={<FilterAltIcon fontSize="small" />}
              sx={{ mb: 2 }}
              action={
                <Link href="/scope-filters" style={{ textDecoration: "none" }}>
                  <Button size="small" color="inherit">Configure Scope Filters</Button>
                </Link>
              }
            >
              Clicking "Confirm Mappings & Run Validation" runs: Silver → <strong>Scope Filter (refreshes dataset;
              master exclusions cascade to related transactions)</strong> → Profiling → Validation → AI Enrichment → Gold.
              Set up business scope rules (e.g. only 2024 shipments, exclude discontinued products) before running,
              or edit rules and re-run afterward from the Scope Filters page.
            </Alert>

            {extractedSummary.extraction_errors && Object.keys(extractedSummary.extraction_errors).length > 0 && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                <strong>Some datasets failed extraction:</strong>{" "}
                {Object.keys(extractedSummary.extraction_errors).join(", ")}
              </Alert>
            )}

            {activeDatasets.map((dataset) => {
              const state = mappings[dataset] || { entries: [], loading: true };
              const pending = state.entries.filter((e) => !e.approved && e.canonical_field).length;
              return (
                <Accordion key={dataset} defaultExpanded={pending > 0}>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 2, width: "100%" }}>
                      <Typography sx={{ fontWeight: 600, flexGrow: 1 }}>
                        {dataset.replace(/_/g, " ")}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {(extractedSummary.datasets[dataset] as any)?.row_count} rows ·{" "}
                        {(extractedSummary.datasets[dataset] as any)?.raw_columns?.length} columns
                      </Typography>
                      {pending > 0 ? (
                        <Chip label={`${pending} to review`} color="warning" size="small" />
                      ) : (
                        <Chip label="All Approved" color="success" size="small" icon={<CheckCircleIcon />} />
                      )}
                    </Box>
                  </AccordionSummary>
                  <AccordionDetails>
                    {state.loading ? (
                      <CircularProgress size={20} />
                    ) : (
                      <Box sx={{ overflowX: "auto" }}>
                        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
                          <thead>
                            <tr style={{ background: "#EEF3FC" }}>
                              <th style={{ padding: "6px 12px", textAlign: "left" }}>Raw Column (Your File)</th>
                              <th style={{ padding: "6px 12px", textAlign: "left" }}>→ Canonical Field</th>
                              <th style={{ padding: "6px 12px", textAlign: "left" }}>Confidence</th>
                              <th style={{ padding: "6px 12px", textAlign: "left" }}>Source</th>
                              <th style={{ padding: "6px 12px", textAlign: "left" }}>Status</th>
                            </tr>
                          </thead>
                          <tbody>
                            {state.entries.map((entry, idx) => (
                              <tr key={entry.raw_column} style={{ borderBottom: "1px solid #E3E9F5" }}>
                                <td style={{ padding: "6px 12px", fontFamily: "monospace" }}>{entry.raw_column}</td>
                                <td style={{ padding: "6px 8px", minWidth: 200 }}>
                                  <Select
                                    size="small"
                                    value={entry.canonical_field || ""}
                                    onChange={(e) => handleOverrideCanonical(dataset, idx, entry.raw_column, e.target.value)}
                                    sx={{ width: "100%", fontSize: 12 }}
                                    displayEmpty
                                  >
                                    <MenuItem value="" sx={{ fontSize: 12, color: "text.secondary", fontStyle: "italic" }}>
                                      — Exclude / not needed —
                                    </MenuItem>
                                    {(datasetCanonicalFields[dataset] || []).map((f) => (
                                      <MenuItem key={f} value={f} sx={{ fontSize: 12 }}>{f}</MenuItem>
                                    ))}
                                  </Select>
                                </td>
                                <td style={{ padding: "6px 12px" }}>
                                  <Chip
                                    label={`${Math.round((entry.confidence ?? 0) * 100)}%`}
                                    size="small"
                                    color={entry.confidence >= 0.9 ? "success" : entry.confidence >= 0.55 ? "warning" : "default"}
                                  />
                                </td>
                                <td style={{ padding: "6px 12px" }}>
                                  <Chip
                                    label={entry.source || "—"}
                                    size="small"
                                    variant="outlined"
                                    color={entry.source === "rule_based" ? "primary" : entry.source === "manual_override" ? "secondary" : "info"}
                                  />
                                </td>
                                <td style={{ padding: "6px 12px" }}>
                                  {entry.approved ? (
                                    <Chip label="Approved" size="small" color="success" icon={<CheckCircleIcon />} />
                                  ) : !entry.canonical_field ? (
                                    <Chip label="Excluded" size="small" color="default" variant="outlined" />
                                  ) : (
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      onClick={() => handleApproveMapping(dataset, entry.raw_column)}
                                    >
                                      Approve
                                    </Button>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </Box>
                    )}
                  </AccordionDetails>
                </Accordion>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* ---- STEP 4: Results ---- */}
      {step === 4 && finalSummary && (
        <>
          <Alert severity="success" icon={<CheckCircleIcon />} sx={{ mb: 3 }}>
            Pipeline complete! Validation and profiling finished for{" "}
            {Object.values(finalSummary.datasets).filter((v) => !(v as any).skipped).length} dataset(s).
          </Alert>

          <Grid container spacing={2} sx={{ mb: 3 }}>
            <Grid item xs={12} sm={6} md={3}>
              <Card>
                <CardContent>
                  <Typography variant="body2" color="text.secondary">Run ID</Typography>
                  <Typography variant="h6" sx={{ color: "primary.main", fontWeight: 700 }}>
                    {finalSummary.run_id.replace("run_", "")}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Card>
                <CardContent>
                  <Typography variant="body2" color="text.secondary">Total Issues</Typography>
                  <Typography variant="h4" sx={{ color: "#D9822B", fontWeight: 700 }}>{finalSummary.issue_count}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Card>
                <CardContent>
                  <Typography variant="body2" color="text.secondary">AI Review Items</Typography>
                  <Typography variant="h4" sx={{ color: "#5B9BD5", fontWeight: 700 }}>{finalSummary.review_queue_count}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Card>
                <CardContent>
                  <Typography variant="body2" color="text.secondary">Cross-Ref Exceptions</Typography>
                  <Typography variant="h4" sx={{ color: "#C1372B", fontWeight: 700 }}>{finalSummary.cross_reference_exception_count}</Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          <Typography variant="h6" sx={{ mb: 2, color: "primary.main" }}>Dataset Results</Typography>
          <Grid container spacing={2} sx={{ mb: 3 }}>
            {Object.entries(finalSummary.datasets).map(([dataset, rawStats]) => {
              const stats = rawStats as any;
              if (stats.skipped) {
                return (
                  <Grid item xs={12} sm={6} md={3} key={dataset}>
                    <Card sx={{ bgcolor: "#F9FAFB" }}>
                      <CardContent>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>{dataset.replace(/_/g, " ")}</Typography>
                        <Chip label="Skipped" size="small" sx={{ mt: 1 }} />
                        <Typography variant="caption" color="text.secondary" display="block">{stats.reason}</Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                );
              }
              return (
                <Grid item xs={12} sm={6} md={3} key={dataset}>
                  <Card>
                    <CardContent>
                      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>{dataset.replace(/_/g, " ")}</Typography>
                      <Typography variant="h5" sx={{ color: "primary.main", fontWeight: 700, mt: 0.5 }}>{stats.row_count} rows</Typography>
                      <Typography variant="caption" color="text.secondary">
                        Valid: {stats.valid} · Review: {stats.needs_review} · Invalid: {stats.invalid}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              );
            })}
          </Grid>

          <Button variant="outlined" onClick={() => { setStep(0); setExtractedSummary(null); setFinalSummary(null); }}>
            Run Another Pipeline
          </Button>
        </>
      )}
    </Box>
  );
}
