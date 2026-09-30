"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import TextField from "@mui/material/TextField";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CableIcon from "@mui/icons-material/Cable";
import SaveIcon from "@mui/icons-material/Save";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import {
  DATASETS,
  DataSourceEntry,
  DataSourceType,
  DatasetQueryConfig,
  getDataSources,
  getOdbcDrivers,
  getSqlConnectionConfig,
  saveSqlConnectionConfig,
  setDataSourceType,
  testSqlConnection,
  uploadDatasetFile,
} from "@/lib/api";

export default function DataSourcesPage() {
  const { refreshSqlStatus } = useProject();
  const [server, setServer] = React.useState("");
  const [database, setDatabase] = React.useState("");
  const [driver, setDriver] = React.useState("ODBC Driver 17 for SQL Server");
  const [drivers, setDrivers] = React.useState<string[]>([]);
  const [queries, setQueries] = React.useState<Record<string, DatasetQueryConfig>>({});
  const [testResult, setTestResult] = React.useState<{ success: boolean; message: string } | null>(null);
  const [testing, setTesting] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [dataSources, setDataSources] = React.useState<Record<string, DataSourceEntry>>({});
  const [uploadStatus, setUploadStatus] = React.useState<Record<string, string>>({});
  const { projectId } = useProject();

  const loadDataSources = React.useCallback(async () => {
    const ds = await getDataSources(projectId);
    setDataSources(ds);
  }, [projectId]);

  React.useEffect(() => {
    getSqlConnectionConfig().then((cfg) => {
      setServer(cfg.connection.server);
      setDatabase(cfg.connection.database);
      setDriver(cfg.connection.driver || "ODBC Driver 17 for SQL Server");
      setQueries(cfg.datasets);
    });
    getOdbcDrivers().then(setDrivers).catch(() => setDrivers(["ODBC Driver 17 for SQL Server"]));
    loadDataSources();
  }, [loadDataSources]);

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testSqlConnection(server, database, driver);
      setTestResult(result);
    } catch (e: any) {
      setTestResult({ success: false, message: e?.message || "Test failed" });
    } finally {
      setTesting(false);
    }
  }

  async function handleSaveSqlConfig() {
    setSaving(true);
    setSaved(false);
    try {
      await saveSqlConnectionConfig(server, database, driver, queries);
      setSaved(true);
      await refreshSqlStatus();
    } finally {
      setSaving(false);
    }
  }

  function updateQuery(dataset: string, query: string) {
    setQueries((prev) => ({ ...prev, [dataset]: { ...prev[dataset], query } }));
  }

  async function handleSourceTypeChange(dataset: string, sourceType: DataSourceType) {
    await setDataSourceType(projectId, dataset, sourceType);
    await loadDataSources();
  }

  async function handleFileUpload(dataset: string, file: File) {
    setUploadStatus((prev) => ({ ...prev, [dataset]: "Uploading..." }));
    try {
      const result = await uploadDatasetFile(projectId, dataset, file);
      setUploadStatus((prev) => ({ ...prev, [dataset]: `Uploaded: ${result.filename}` }));
      await loadDataSources();
    } catch (e: any) {
      setUploadStatus((prev) => ({ ...prev, [dataset]: `Error: ${e?.response?.data?.detail || e.message}` }));
    }
  }

  const configuredCount = Object.values(dataSources).filter((d) => d.source_type !== "none").length;

  return (
    <Box>
      <PageHeader
        title="Data Sources"
        subtitle="Connect to SQL Server or upload CSV/XLSX files directly — per dataset. Any dataset can be left unconfigured; the app runs with whatever data is available."
      />

      <Alert severity={configuredCount > 0 ? "success" : "info"} sx={{ mb: 3 }}>
        {configuredCount} of {DATASETS.length} datasets have a configured source. Datasets left as
        "None" are simply skipped during pipeline runs — no dataset is mandatory.
      </Alert>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
            SQL Server Connection (shared across all SQL-sourced datasets)
          </Typography>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
            <TextField
              label="Server / Instance"
              placeholder="e.g. SQLSRV01 or SQLSRV01\INSTANCE"
              value={server}
              onChange={(e) => setServer(e.target.value)}
              fullWidth
            />
            <TextField
              label="Database"
              placeholder="e.g. ERP_PROD"
              value={database}
              onChange={(e) => setDatabase(e.target.value)}
              fullWidth
            />
            <Select value={driver} onChange={(e) => setDriver(e.target.value)} sx={{ minWidth: 260 }}>
              {(drivers.length ? drivers : [driver]).map((d) => (
                <MenuItem key={d} value={d}>
                  {d}
                </MenuItem>
              ))}
            </Select>
          </Stack>
          <Alert severity="info" sx={{ mb: 2 }}>
            Uses Windows/Integrated Authentication (Trusted_Connection=yes). Your current Windows login
            must have access to this SQL Server instance and database.
          </Alert>
          <Stack direction="row" spacing={2}>
            <Button
              variant="outlined"
              startIcon={<CableIcon />}
              onClick={handleTest}
              disabled={testing || !server || !database}
            >
              {testing ? "Testing..." : "Test Connection"}
            </Button>
            <Button
              variant="contained"
              startIcon={<SaveIcon />}
              onClick={handleSaveSqlConfig}
              disabled={saving || !server || !database}
            >
              {saving ? "Saving..." : "Save Connection"}
            </Button>
          </Stack>
          {testResult && (
            <Alert severity={testResult.success ? "success" : "error"} sx={{ mt: 2 }}>
              {testResult.message}
            </Alert>
          )}
          {saved && (
            <Alert severity="success" icon={<CheckCircleIcon />} sx={{ mt: 2 }}>
              Connection saved. Assign datasets to "SQL" below to use it.
            </Alert>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
            Per-Dataset Source Configuration
          </Typography>
          {DATASETS.map((dataset) => {
            const entry = dataSources[dataset] || { source_type: "none" as DataSourceType };
            // Display labels for shipment flow datasets
            const DISPLAY_LABELS: Record<string, { label: string; badge?: string; badgeColor?: "error" | "info" | "primary" }> = {
              inbound_shipment_history: { label: "Inbound Shipment History", badge: "INBOUND", badgeColor: "info" },
              outbound_shipment_history: { label: "Outbound Shipment History", badge: "OUTBOUND", badgeColor: "primary" },
            };
            const displayInfo = DISPLAY_LABELS[dataset];
            const displayName = displayInfo?.label || dataset.replace(/_/g, " ");
            return (
              <Accordion key={dataset}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box sx={{ display: "flex", alignItems: "center", gap: 2, width: "100%" }}>
                    <Typography sx={{ fontWeight: 600, flexGrow: 1 }}>{displayName}</Typography>
                    {displayInfo?.badge && (
                      <Chip label={displayInfo.badge} size="small" color={displayInfo.badgeColor} variant="outlined" />
                    )}
                    <Chip
                      label={entry.source_type === "none" ? "Not Configured" : entry.source_type.toUpperCase()}
                      size="small"
                      color={entry.source_type === "none" ? "default" : "success"}
                    />
                  </Box>
                </AccordionSummary>
                <AccordionDetails>
                  <ToggleButtonGroup
                    value={entry.source_type}
                    exclusive
                    size="small"
                    onChange={(_, v) => v && handleSourceTypeChange(dataset, v)}
                    sx={{ mb: 2 }}
                  >
                    <ToggleButton value="sql">SQL</ToggleButton>
                    <ToggleButton value="file">Upload File</ToggleButton>
                    <ToggleButton value="none">None (Skip)</ToggleButton>
                  </ToggleButtonGroup>

                  {entry.source_type === "sql" && (
                    <TextField
                      fullWidth
                      multiline
                      minRows={2}
                      label="SQL Query"
                      value={queries[dataset]?.query || ""}
                      onChange={(e) => updateQuery(dataset, e.target.value)}
                      sx={{ mt: 1 }}
                    />
                  )}

                  {entry.source_type === "file" && (
                    <Box sx={{ mt: 1 }}>
                      <Button variant="outlined" component="label" startIcon={<UploadFileIcon />}>
                        Choose CSV/XLSX File
                        <input
                          type="file"
                          hidden
                          accept=".csv,.xlsx,.xls"
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) handleFileUpload(dataset, file);
                          }}
                        />
                      </Button>
                      {(entry.uploaded_filename || uploadStatus[dataset]) && (
                        <Typography variant="body2" sx={{ mt: 1 }} color="text.secondary">
                          {uploadStatus[dataset] ||
                            (entry.uploaded_filename ? `Current file: ${entry.uploaded_filename}` : "")}
                        </Typography>
                      )}
                    </Box>
                  )}

                  {entry.source_type === "none" && (
                    <Typography variant="body2" color="text.secondary">
                      This dataset will be skipped during pipeline runs. Set it to SQL or Upload File
                      to include it.
                    </Typography>
                  )}
                </AccordionDetails>
              </Accordion>
            );
          })}
        </CardContent>
      </Card>
    </Box>
  );
}
