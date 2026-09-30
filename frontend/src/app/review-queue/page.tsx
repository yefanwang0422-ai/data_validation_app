"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import { getReviewQueue, submitReviewDecision, DATASETS } from "@/lib/api";

export default function ReviewQueuePage() {
  const { projectId, runId } = useProject();
  const [dataset, setDataset] = React.useState<string>("customer_master");
  const [rows, setRows] = React.useState<any[]>([]);

  const load = React.useCallback(() => {
    if (runId) {
      getReviewQueue(projectId, runId, dataset)
        .then((res) => setRows(res.records.map((r, i) => ({ id: i, ...r }))))
        .catch(() => setRows([]));
    }
  }, [projectId, runId, dataset]);

  React.useEffect(() => {
    load();
  }, [load]);

  async function decide(recordIndex: number, decision: string) {
    if (!runId) return;
    await submitReviewDecision(projectId, runId, dataset, recordIndex, { decision, reviewer: "web_ui" });
    load();
  }

  const columns: GridColDef[] = [
    { field: "record_id", headerName: "Record ID", width: 130 },
    { field: "field", headerName: "Field", width: 120 },
    { field: "candidate_value", headerName: "AI Candidate Value", width: 170 },
    {
      field: "confidence",
      headerName: "Confidence",
      width: 120,
      renderCell: (params) => (
        <Chip
          label={`${Math.round((params.value ?? 0) * 100)}%`}
          size="small"
          color={params.value >= 0.8 ? "success" : params.value >= 0.5 ? "warning" : "default"}
        />
      ),
    },
    { field: "rationale", headerName: "Rationale", flex: 1, minWidth: 260 },
    {
      field: "applied",
      headerName: "Applied",
      width: 100,
      renderCell: (params) => (params.value ? <Chip label="Yes" size="small" color="info" /> : "No"),
    },
    {
      field: "actions",
      headerName: "Review",
      width: 220,
      sortable: false,
      renderCell: (params) => (
        <Stack direction="row" spacing={1}>
          <Button size="small" color="success" variant="outlined" onClick={() => decide(params.row.id, "approve")}>
            Approve
          </Button>
          <Button size="small" color="error" variant="outlined" onClick={() => decide(params.row.id, "reject")}>
            Reject
          </Button>
        </Stack>
      ),
    },
  ];

  return (
    <Box>
      <PageHeader
        title="AI-Fill Review Queue"
        subtitle="Every AI-assisted geographic fill requires manual approval before being treated as confirmed"
        actions={
          <Select size="small" value={dataset} onChange={(e) => setDataset(e.target.value)}>
            {DATASETS.map((d) => (
              <MenuItem key={d} value={d}>
                {d.replace(/_/g, " ")}
              </MenuItem>
            ))}
          </Select>
        }
      />
      <Box sx={{ height: 600, bgcolor: "#fff", borderRadius: 2 }}>
        <DataGrid rows={rows} columns={columns} pageSizeOptions={[10, 25, 50]} />
      </Box>
    </Box>
  );
}
