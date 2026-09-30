"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Chip from "@mui/material/Chip";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import PageHeader from "@/components/PageHeader";
import StatusFilterToggle from "@/components/StatusFilterToggle";
import { useProject } from "@/components/ProjectContext";
import { getRawVsValidated, DATASETS, StatusFilter } from "@/lib/api";

export default function RecordDetailPage() {
  const { projectId, runId } = useProject();
  const [dataset, setDataset] = React.useState<string>(DATASETS[0]);
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>("all");
  const [rows, setRows] = React.useState<any[]>([]);
  const [columns, setColumns] = React.useState<GridColDef[]>([]);

  React.useEffect(() => {
    if (runId) {
      getRawVsValidated(projectId, runId, dataset, statusFilter)
        .then((res) => {
          const records = res.records.map((r, i) => ({ id: i, ...r }));
          setRows(records);
          if (records.length > 0) {
            const cols: GridColDef[] = Object.keys(records[0])
              .filter((k) => k !== "id")
              .map((k) => ({
                field: k,
                headerName: k.replace(/_/g, " "),
                width: k === "row_status" ? 140 : 150,
                renderCell:
                  k === "row_status"
                    ? (params: any) => (
                        <Chip
                          label={params.value}
                          size="small"
                          color={
                            params.value === "valid"
                              ? "success"
                              : params.value === "needs_review"
                              ? "warning"
                              : "error"
                          }
                        />
                      )
                    : undefined,
              }));
            setColumns(cols);
          }
        })
        .catch(() => setRows([]));
    }
  }, [projectId, runId, dataset, statusFilter]);

  return (
    <Box>
      <PageHeader
        title="Record Detail (Raw vs Validated)"
        subtitle="Full Gold-layer record view with validation status and flags"
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
      <Box sx={{ mb: 2 }}>
        <StatusFilterToggle value={statusFilter} onChange={setStatusFilter} />
      </Box>
      <Box sx={{ height: 600, bgcolor: "#fff", borderRadius: 2 }}>
        <DataGrid rows={rows} columns={columns} pageSizeOptions={[10, 25, 50]} />
      </Box>
    </Box>
  );
}
