"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Alert from "@mui/material/Alert";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import { exportRun, optilogicExportUrl, DATASETS } from "@/lib/api";

export default function ExportPage() {
  const { projectId, runId } = useProject();
  const [dataset, setDataset] = React.useState<string>(DATASETS[0]);
  const [outputs, setOutputs] = React.useState<Record<string, string> | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function handleExportAll() {
    if (!runId) return;
    setLoading(true);
    try {
      const result = await exportRun(projectId, runId);
      setOutputs(result);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Box>
      <PageHeader
        title="Export / Download"
        subtitle="Gold datasets, issue log, review queue, cross-reference exceptions, and Optilogic-ready exports"
      />

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
            Generate All Exports for This Run
          </Typography>
          <Button variant="contained" startIcon={<FileDownloadIcon />} onClick={handleExportAll} disabled={loading || !runId}>
            {loading ? "Generating..." : "Generate All Exports"}
          </Button>
          {outputs && (
            <pre style={{ marginTop: 16, fontSize: 12, background: "#F4F7FB", padding: 12, borderRadius: 8 }}>
              {JSON.stringify(outputs, null, 2)}
            </pre>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
            Optilogic / Cosmic Frog-Ready Export (Single Dataset)
          </Typography>
          <Stack direction="row" spacing={2} alignItems="center">
            <Select size="small" value={dataset} onChange={(e) => setDataset(e.target.value)}>
              {DATASETS.map((d) => (
                <MenuItem key={d} value={d}>
                  {d.replace(/_/g, " ")}
                </MenuItem>
              ))}
            </Select>
            <Button
              variant="outlined"
              startIcon={<FileDownloadIcon />}
              component="a"
              href={runId ? optilogicExportUrl(projectId, runId, dataset) : undefined}
              disabled={!runId}
            >
              Download Optilogic CSV
            </Button>
          </Stack>
          {!runId && (
            <Alert severity="warning" sx={{ mt: 2 }}>
              Run the pipeline first to enable exports.
            </Alert>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
