"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Chip from "@mui/material/Chip";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import { DataGrid, GridColDef, GridRenderCellParams } from "@mui/x-data-grid";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import { getCrossReferenceExceptions, DATASETS } from "@/lib/api";

export default function CrossReferencePage() {
  const { projectId, runId } = useProject();
  const [dataset, setDataset] = React.useState<string>("shipment_history");
  const [rows, setRows] = React.useState<any[]>([]);
  const [totalCount, setTotalCount] = React.useState<number>(0);
  const [uniqueCount, setUniqueCount] = React.useState<number>(0);

  React.useEffect(() => {
    if (runId) {
      getCrossReferenceExceptions(projectId, runId, dataset)
        .then((res: any) => {
          setRows((res.records || []).map((r: any, i: number) => ({ id: i, ...r })));
          setTotalCount(res.count ?? 0);
          setUniqueCount(res.unique_exception_count ?? res.records?.length ?? 0);
        })
        .catch(() => { setRows([]); setTotalCount(0); setUniqueCount(0); });
    }
  }, [projectId, runId, dataset]);

  const columns: GridColDef[] = [
    {
      field: "count",
      headerName: "Count",
      width: 90,
      renderCell: (params: GridRenderCellParams) => (
        <Chip
          label={params.value ?? 1}
          size="small"
          color={(params.value ?? 1) > 1 ? "error" : "default"}
          sx={{ fontWeight: 700 }}
        />
      ),
    },
    { field: "field", headerName: "Field", width: 200 },
    { field: "invalid_value", headerName: "Value in Data", width: 160 },
    {
      field: "match_type",
      headerName: "Match Type",
      width: 160,
      renderCell: (params: GridRenderCellParams) => {
        const val = params.value;
        if (val === "prefix_stripped") {
          return <Chip label="Prefix Match" size="small" color="warning" variant="outlined" />;
        }
        if (val === "no_match") {
          return <Chip label="No Match" size="small" color="error" variant="outlined" />;
        }
        return <Chip label={val || "—"} size="small" />;
      },
    },
    { field: "matched_value", headerName: "Matched Master Key", width: 180 },
    { field: "expected_master", headerName: "Expected Master Table", width: 200 },
    { field: "record_id", headerName: "First Record ID", width: 150 },
    { field: "detected_at", headerName: "Detected At", flex: 1, minWidth: 180 },
  ];

  return (
    <Box>
      <PageHeader
        title="Cross-Reference Exceptions"
        subtitle="Transactional records whose foreign keys don't match any master record. Rows are grouped by unique (field, value, master) combination — Count shows how many records share the same issue."
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

      {totalCount > 0 && (
        <Alert severity={uniqueCount < totalCount ? "warning" : "error"} sx={{ mb: 2 }}>
          <strong>{totalCount} total exception records</strong> consolidated into{" "}
          <strong>{uniqueCount} unique issues</strong>.
          {totalCount > uniqueCount && (
            <> The same issue repeats across {totalCount - uniqueCount} additional records.</>
          )}
        </Alert>
      )}

      <Box sx={{ height: 600, bgcolor: "#fff", borderRadius: 2 }}>
        <DataGrid
          rows={rows}
          columns={columns}
          pageSizeOptions={[10, 25, 50]}
          initialState={{ sorting: { sortModel: [{ field: "count", sort: "desc" }] } }}
        />
      </Box>
    </Box>
  );
}
