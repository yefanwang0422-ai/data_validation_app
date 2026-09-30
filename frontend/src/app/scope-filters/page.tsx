"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Button from "@mui/material/Button";
import TextField from "@mui/material/TextField";
import Chip from "@mui/material/Chip";
import Alert from "@mui/material/Alert";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import IconButton from "@mui/material/IconButton";
import Table from "@mui/material/Table";
import TableHead from "@mui/material/TableHead";
import TableBody from "@mui/material/TableBody";
import TableRow from "@mui/material/TableRow";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import Paper from "@mui/material/Paper";
import CircularProgress from "@mui/material/CircularProgress";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import SaveIcon from "@mui/icons-material/Save";
import FilterAltIcon from "@mui/icons-material/FilterAlt";
import ReplayIcon from "@mui/icons-material/Replay";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import {
  DATASETS,
  getCanonicalFields,
  getDatasetScopeFilters,
  saveDatasetScopeFilters,
  runFromBronze,
  ScopeRule,
  RunSummary,
} from "@/lib/api";

const RULE_TYPES = [
  { value: "date_range", label: "Date Range" },
  { value: "include_values", label: "Include Only These Values" },
  { value: "exclude_values", label: "Exclude These Values" },
  { value: "numeric_range", label: "Numeric Range" },
];

function emptyRule(): ScopeRule {
  return { type: "include_values", field: "", description: "", values: [] };
}

export default function ScopeFiltersPage() {
  const { projectId, runId, refreshRuns } = useProject();
  const [expandedDataset, setExpandedDataset] = React.useState<string | null>(null);
  const [fieldsByDataset, setFieldsByDataset] = React.useState<Record<string, string[]>>({});
  const [rulesByDataset, setRulesByDataset] = React.useState<Record<string, ScopeRule[]>>({});
  const [loadingDataset, setLoadingDataset] = React.useState<string | null>(null);
  const [savingDataset, setSavingDataset] = React.useState<string | null>(null);
  const [savedMsg, setSavedMsg] = React.useState<Record<string, string>>({});
  const [error, setError] = React.useState<string | null>(null);
  const [rerunning, setRerunning] = React.useState(false);
  const [rerunResult, setRerunResult] = React.useState<RunSummary | null>(null);
  const [rerunError, setRerunError] = React.useState<string | null>(null);

  async function loadDataset(dataset: string) {
    setLoadingDataset(dataset);
    setError(null);
    try {
      const [fields, existing] = await Promise.all([
        getCanonicalFields(dataset).catch(() => []),
        getDatasetScopeFilters(projectId, dataset),
      ]);
      setFieldsByDataset((prev) => ({ ...prev, [dataset]: fields }));
      setRulesByDataset((prev) => ({ ...prev, [dataset]: existing.rules || [] }));
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || `Failed to load ${dataset}`);
    } finally {
      setLoadingDataset(null);
    }
  }

  function handleExpand(dataset: string) {
    const next = expandedDataset === dataset ? null : dataset;
    setExpandedDataset(next);
    if (next && !rulesByDataset[dataset]) {
      loadDataset(dataset);
    }
  }

  function addRule(dataset: string) {
    setRulesByDataset((prev) => ({
      ...prev,
      [dataset]: [...(prev[dataset] || []), emptyRule()],
    }));
  }

  function removeRule(dataset: string, idx: number) {
    setRulesByDataset((prev) => ({
      ...prev,
      [dataset]: (prev[dataset] || []).filter((_, i) => i !== idx),
    }));
  }

  function updateRule(dataset: string, idx: number, patch: Partial<ScopeRule>) {
    setRulesByDataset((prev) => ({
      ...prev,
      [dataset]: (prev[dataset] || []).map((r, i) => (i === idx ? { ...r, ...patch } : r)),
    }));
  }

  async function handleSave(dataset: string) {
    setSavingDataset(dataset);
    setError(null);
    try {
      const rules = rulesByDataset[dataset] || [];
      await saveDatasetScopeFilters(projectId, dataset, rules);
      setSavedMsg((prev) => ({ ...prev, [dataset]: `Saved ${rules.length} rule(s). Applies on next pipeline run.` }));
      setTimeout(() => setSavedMsg((prev) => ({ ...prev, [dataset]: "" })), 4000);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || "Save failed");
    } finally {
      setSavingDataset(null);
    }
  }

  // ---- Re-run pipeline from existing Bronze data (Silver → Scope Filter → Profile → Validate → Gold) ----
  // Scope rules are only applied when the pipeline runs, so after editing/saving rules the current
  // run's Gold/Silver data must be refreshed by re-running from Bronze (no re-extraction needed).
  async function handleRerunPipeline() {
    if (!runId) {
      setRerunError("No active run selected. Run the pipeline once from the Run Pipeline page first.");
      return;
    }
    setRerunning(true);
    setRerunError(null);
    setRerunResult(null);
    try {
      const result = await runFromBronze(projectId, runId);
      setRerunResult(result);
      await refreshRuns();
    } catch (e: any) {
      setRerunError(e?.response?.data?.detail || e.message || "Re-run failed");
    } finally {
      setRerunning(false);
    }
  }

  const RuleEditor = ({ dataset, rule, idx }: { dataset: string; rule: ScopeRule; idx: number }) => {
    const fields = fieldsByDataset[dataset] || [];
    return (
      <TableRow sx={{ "&:hover": { bgcolor: "#F9FAFB" } }}>
        <TableCell sx={{ minWidth: 160 }}>
          <Select
            size="small"
            fullWidth
            value={rule.type}
            onChange={(e) => updateRule(dataset, idx, { type: e.target.value as ScopeRule["type"] })}
          >
            {RULE_TYPES.map((t) => (
              <MenuItem key={t.value} value={t.value} sx={{ fontSize: 13 }}>{t.label}</MenuItem>
            ))}
          </Select>
        </TableCell>
        <TableCell sx={{ minWidth: 160 }}>
          <Select
            size="small"
            fullWidth
            displayEmpty
            value={rule.field}
            onChange={(e) => updateRule(dataset, idx, { field: e.target.value })}
          >
            <MenuItem value="" sx={{ fontSize: 13, fontStyle: "italic", color: "text.secondary" }}>— select field —</MenuItem>
            {fields.map((f) => (
              <MenuItem key={f} value={f} sx={{ fontSize: 13 }}>{f}</MenuItem>
            ))}
          </Select>
        </TableCell>
        <TableCell sx={{ minWidth: 260 }}>
          {rule.type === "date_range" && (
            <Box sx={{ display: "flex", gap: 1 }}>
              <TextField
                size="small" type="date" label="Start"
                value={rule.start || ""}
                onChange={(e) => updateRule(dataset, idx, { start: e.target.value })}
                InputLabelProps={{ shrink: true }}
              />
              <TextField
                size="small" type="date" label="End"
                value={rule.end || ""}
                onChange={(e) => updateRule(dataset, idx, { end: e.target.value })}
                InputLabelProps={{ shrink: true }}
              />
            </Box>
          )}
          {(rule.type === "include_values" || rule.type === "exclude_values") && (
            <TextField
              size="small" fullWidth
              label="Comma-separated values"
              placeholder="Electronics, Chemicals"
              value={(rule.values || []).join(", ")}
              onChange={(e) =>
                updateRule(dataset, idx, {
                  values: e.target.value.split(",").map((v) => v.trim()).filter(Boolean),
                })
              }
            />
          )}
          {rule.type === "numeric_range" && (
            <Box sx={{ display: "flex", gap: 1 }}>
              <TextField
                size="small" type="number" label="Min"
                value={rule.min ?? ""}
                onChange={(e) => updateRule(dataset, idx, { min: e.target.value === "" ? undefined : Number(e.target.value) })}
              />
              <TextField
                size="small" type="number" label="Max"
                value={rule.max ?? ""}
                onChange={(e) => updateRule(dataset, idx, { max: e.target.value === "" ? undefined : Number(e.target.value) })}
              />
            </Box>
          )}
        </TableCell>
        <TableCell sx={{ minWidth: 180 }}>
          <TextField
            size="small" fullWidth
            placeholder="e.g. 2024 shipments only"
            value={rule.description || ""}
            onChange={(e) => updateRule(dataset, idx, { description: e.target.value })}
          />
        </TableCell>
        <TableCell>
          <IconButton size="small" color="error" onClick={() => removeRule(dataset, idx)}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </TableCell>
      </TableRow>
    );
  };

  return (
    <Box>
      <PageHeader
        title="Scope Filters"
        subtitle="Define which records count toward business analysis (separate from data quality). Records are never deleted — excluded rows remain fully auditable in Gold and are shown in the Business Insights Excluded view."
      />

      <Card sx={{ mb: 3, bgcolor: "#F8FAFF" }}>
        <CardContent>
          <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
            <Box sx={{ flexGrow: 1 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                Apply Rule Changes to Current Run
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Scope rules only take effect when the pipeline runs. After saving rule changes above, click
                "Re-run Pipeline" to refresh Silver → Scope Filter (incl. master→transaction cascade) → Profiling
                → Validation → AI Enrichment → Gold for the current run{runId ? ` (${runId.replace("run_", "")})` : ""}
                — no re-extraction needed, Bronze data is reused as-is.
              </Typography>
            </Box>
            <Button
              variant="contained"
              color="secondary"
              startIcon={rerunning ? <CircularProgress size={16} color="inherit" /> : <ReplayIcon />}
              onClick={handleRerunPipeline}
              disabled={rerunning || !runId}
            >
              {rerunning ? "Re-running..." : "Re-run Pipeline"}
            </Button>
          </Box>

          {rerunError && <Alert severity="error" sx={{ mt: 2 }}>{rerunError}</Alert>}

          {rerunResult && (
            <Alert severity="success" sx={{ mt: 2 }}>
              Pipeline re-run complete for run <strong>{rerunResult.run_id.replace("run_", "")}</strong>.
              {" "}
              {Object.entries(rerunResult.datasets)
                .filter(([, v]) => !(v as any).skipped)
                .map(([ds, v]: [string, any]) =>
                  v.scope_excluded !== undefined ? `${ds}: ${v.scope_excluded} excluded` : null
                )
                .filter(Boolean)
                .join(" · ") || "No scope exclusions on any dataset."}
              {" "}View details on the Business Insights or Data Stage Viewer pages.
            </Alert>
          )}
        </CardContent>
      </Card>

      {error && <Alert severity="error" sx={{ mb: 3 }}>{error}</Alert>}

      {DATASETS.map((dataset) => {
        const rules = rulesByDataset[dataset] || [];
        const isExpanded = expandedDataset === dataset;
        return (
          <Accordion
            key={dataset}
            expanded={isExpanded}
            onChange={() => handleExpand(dataset)}
            sx={{ mb: 1 }}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 2, width: "100%" }}>
                <FilterAltIcon fontSize="small" sx={{ color: "primary.main" }} />
                <Typography sx={{ fontWeight: 600, flexGrow: 1 }}>{dataset.replace(/_/g, " ")}</Typography>
                {rules.length > 0 ? (
                  <Chip label={`${rules.length} rule(s)`} color="primary" size="small" variant="outlined" />
                ) : (
                  <Chip label="No rules — all in scope" size="small" variant="outlined" />
                )}
              </Box>
            </AccordionSummary>
            <AccordionDetails>
              {loadingDataset === dataset ? (
                <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
                  <CircularProgress size={24} />
                </Box>
              ) : (
                <>
                  {rules.length === 0 ? (
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                      No scope rules configured — all records in this dataset are treated as in-scope for business analysis.
                    </Typography>
                  ) : (
                    <TableContainer component={Paper} variant="outlined" sx={{ mb: 2 }}>
                      <Table size="small">
                        <TableHead>
                          <TableRow sx={{ bgcolor: "#EEF3FC" }}>
                            <TableCell sx={{ fontWeight: 600 }}>Rule Type</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Field</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Condition</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}>Description</TableCell>
                            <TableCell sx={{ fontWeight: 600 }}></TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {rules.map((rule, idx) => (
                            <RuleEditor key={idx} dataset={dataset} rule={rule} idx={idx} />
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )}

                  <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<AddIcon />}
                      onClick={() => addRule(dataset)}
                    >
                      Add Rule
                    </Button>
                    <Button
                      size="small"
                      variant="contained"
                      startIcon={savingDataset === dataset ? <CircularProgress size={14} color="inherit" /> : <SaveIcon />}
                      onClick={() => handleSave(dataset)}
                      disabled={savingDataset === dataset}
                    >
                      {savingDataset === dataset ? "Saving..." : "Save Rules"}
                    </Button>
                    {savedMsg[dataset] && (
                      <Typography variant="caption" color="success.main" sx={{ ml: 1 }}>
                        ✓ {savedMsg[dataset]}
                      </Typography>
                    )}
                  </Box>
                </>
              )}
            </AccordionDetails>
          </Accordion>
        );
      })}
    </Box>
  );
}
