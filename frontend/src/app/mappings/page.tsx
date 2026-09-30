"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import Stack from "@mui/material/Stack";
import { DataGrid, GridColDef, GridRenderCellParams } from "@mui/x-data-grid";
import RefreshIcon from "@mui/icons-material/Refresh";
import CheckIcon from "@mui/icons-material/Check";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import { getMapping, approveMapping, getCanonicalFields, DATASETS, api } from "@/lib/api";

export default function MappingReviewPage() {
  const { projectId } = useProject();
  const [dataset, setDataset] = React.useState<string>(DATASETS[0]);
  const [rows, setRows] = React.useState<any[]>([]);
  const [refreshing, setRefreshing] = React.useState(false);
  const [refreshMsg, setRefreshMsg] = React.useState<string | null>(null);
  const [canonicalFields, setCanonicalFields] = React.useState<string[]>([]);

  const load = React.useCallback(() => {
    getMapping(projectId, dataset)
      .then((res) => setRows(res.entries.map((r, i) => ({ id: i, ...r }))))
      .catch(() => setRows([]));
  }, [projectId, dataset]);

  // Reload canonical fields whenever the dataset changes
  React.useEffect(() => {
    getCanonicalFields(dataset)
      .then(setCanonicalFields)
      .catch(() => setCanonicalFields([]));
  }, [dataset]);

  React.useEffect(() => {
    setRefreshMsg(null);
    load();
  }, [load]);

  async function handleApprove(rawColumn: string) {
    await approveMapping(projectId, dataset, rawColumn);
    load();
  }

  async function handleRefreshMapping() {
    setRefreshing(true);
    setRefreshMsg(null);
    try {
      const res = await api.post(`/mappings/${projectId}/${dataset}/refresh`);
      setRefreshMsg(
        `Mapping refreshed: ${res.data.entries?.filter((e: any) => e.approved).length ?? 0} auto-approved.`
      );
      load();
    } catch (e: any) {
      setRefreshMsg(`Error: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setRefreshing(false);
    }
  }

  async function handleOverrideCanonical(rowId: number, rawColumn: string, newCanonicalField: string) {
    // Patch the entire entries list with the updated canonical field, then auto-approve it.
    const updatedEntries = rows.map((r) => {
      if (r.id === rowId) {
        return { ...r, canonical_field: newCanonicalField, source: "manual_override", approved: false };
      }
      return r;
    });
    // Strip client-side id field before saving
    const payload = updatedEntries.map(({ id, ...rest }) => rest);
    await api.post(`/mappings/${projectId}/${dataset}/patch`, { entries: payload });
    await approveMapping(projectId, dataset, rawColumn);
    load();
  }

  const columns: GridColDef[] = [
    { field: "raw_column", headerName: "Raw Column (Your File)", width: 200 },
    {
      field: "canonical_field",
      headerName: "Canonical Field",
      width: 230,
      renderCell: (params: GridRenderCellParams) => (
        <Select
          size="small"
          value={params.value || ""}
          onChange={(e) => handleOverrideCanonical(params.row.id, params.row.raw_column, e.target.value)}
          sx={{ width: "100%", fontSize: 13 }}
          displayEmpty
        >
          <MenuItem value="" sx={{ fontSize: 13, color: "text.secondary", fontStyle: "italic" }}>
            — Exclude / not needed —
          </MenuItem>
          {canonicalFields.map((f) => (
            <MenuItem key={f} value={f} sx={{ fontSize: 13 }}>{f}</MenuItem>
          ))}
        </Select>
      ),
    },
    {
      field: "confidence",
      headerName: "Confidence",
      width: 110,
      renderCell: (params: GridRenderCellParams) => (
        <Chip
          label={`${Math.round((params.value ?? 0) * 100)}%`}
          size="small"
          color={params.value >= 0.9 ? "success" : params.value >= 0.55 ? "warning" : "default"}
        />
      ),
    },
    {
      field: "source",
      headerName: "Source",
      width: 140,
      renderCell: (params: GridRenderCellParams) => (
        <Chip
          label={params.value || "—"}
          size="small"
          color={
            params.value === "rule_based"
              ? "primary"
              : params.value === "manual_override"
              ? "secondary"
              : "info"
          }
          variant="outlined"
        />
      ),
    },
    {
      field: "approved",
      headerName: "Status",
      width: 180,
      renderCell: (params: GridRenderCellParams) =>
        params.value ? (
          <Chip label="Approved" size="small" color="success" icon={<CheckIcon />} />
        ) : !params.row.canonical_field ? (
          <Chip label="Excluded" size="small" color="default" variant="outlined" />
        ) : (
          <Button
            size="small"
            variant="outlined"
            color="primary"
            onClick={() => handleApprove(params.row.raw_column)}
          >
            Approve
          </Button>
        ),
    },
    { field: "rationale", headerName: "Rationale / Notes", flex: 1, minWidth: 260 },
  ];

  return (
    <Box>
      <PageHeader
        title="Column Mapping Review"
        subtitle="Map your file's raw column names to canonical Silver/Gold field names. Use the dropdown to override any suggestion, then Approve."
        actions={
          <Stack direction="row" spacing={2} alignItems="center">
            <Select
              size="small"
              value={dataset}
              onChange={(e) => { setDataset(e.target.value); setRefreshMsg(null); }}
            >
              {DATASETS.map((d) => (
                <MenuItem key={d} value={d}>
                  {d.replace(/_/g, " ")}
                </MenuItem>
              ))}
            </Select>
            <Button
              variant="outlined"
              startIcon={<RefreshIcon />}
              onClick={handleRefreshMapping}
              disabled={refreshing}
            >
              {refreshing ? "Refreshing..." : "Re-run AI Mapping"}
            </Button>
          </Stack>
        }
      />

      {refreshMsg && (
        <Alert severity={refreshMsg.startsWith("Error") ? "error" : "success"} sx={{ mb: 2 }}>
          {refreshMsg}
        </Alert>
      )}

      {rows.length === 0 ? (
        <Alert severity="info">
          No column mapping found for this dataset. Upload a file on the Data Sources screen, or run
          the pipeline once, to generate suggestions automatically.
        </Alert>
      ) : (
        <Box sx={{ height: 620, bgcolor: "#fff", borderRadius: 2 }}>
          <DataGrid
            rows={rows}
            columns={columns}
            pageSizeOptions={[10, 25, 50]}
            rowHeight={52}
          />
        </Box>
      )}
    </Box>
  );
}
