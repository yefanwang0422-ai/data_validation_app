"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import { api, DATASETS } from "@/lib/api";

export default function ProfilingPage() {
  const { projectId, runId } = useProject();
  const [dataset, setDataset] = React.useState<string>(DATASETS[0]);
  const [profile, setProfile] = React.useState<any>(null);

  React.useEffect(() => {
    if (runId) {
      api
        .get(`/runs/${projectId}/${runId}/profile/${dataset}`)
        .then((res) => setProfile(res.data))
        .catch(() => setProfile(null));
    }
  }, [projectId, runId, dataset]);

  const rows = profile
    ? Object.entries(profile.profile.columns).map(([col, info]: [string, any], i) => ({
        id: i,
        column: col,
        ...info,
      }))
    : [];

  const columns: GridColDef[] = [
    { field: "column", headerName: "Column", width: 180 },
    { field: "dtype", headerName: "Type", width: 100 },
    { field: "null_count", headerName: "Nulls", width: 90 },
    { field: "null_pct", headerName: "Null %", width: 90 },
    { field: "distinct_count", headerName: "Distinct", width: 100 },
    { field: "min", headerName: "Min", width: 100 },
    { field: "max", headerName: "Max", width: 100 },
    { field: "mean", headerName: "Mean", width: 100 },
  ];

  const drift = profile?.schema_drift;

  return (
    <Box>
      <PageHeader
        title="Profiling Report"
        subtitle="Null rates, distributions, and schema drift vs. the previous run"
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

      {drift && (
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
              Schema Drift vs. Previous Run
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap">
              <Chip label={`New columns: ${drift.new_columns.length}`} color="info" size="small" />
              <Chip label={`Removed columns: ${drift.removed_columns.length}`} color="warning" size="small" />
              <Chip label={`Type changes: ${drift.type_changes.length}`} color="error" size="small" />
            </Stack>
          </CardContent>
        </Card>
      )}

      <Box sx={{ height: 500, bgcolor: "#fff", borderRadius: 2 }}>
        <DataGrid rows={rows} columns={columns} pageSizeOptions={[10, 25, 50]} />
      </Box>
    </Box>
  );
}
