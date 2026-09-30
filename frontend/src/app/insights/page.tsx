"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import Chip from "@mui/material/Chip";
import Table from "@mui/material/Table";
import TableHead from "@mui/material/TableHead";
import TableBody from "@mui/material/TableBody";
import TableRow from "@mui/material/TableRow";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import Paper from "@mui/material/Paper";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import VisibilityOffIcon from "@mui/icons-material/VisibilityOff";
import PageHeader from "@/components/PageHeader";
import StatusFilterToggle from "@/components/StatusFilterToggle";
import { useProject } from "@/components/ProjectContext";
import {
  getBusinessMetric,
  getScopeSummary,
  getExcludedRecords,
  getInboundFlowMap,
  getOutboundFlowMap,
  FlowMapResponse,
  ScopeSummaryEntry,
  StatusFilter,
} from "@/lib/api";
import { CHART_BLUE_SEQUENCE } from "@/theme/theme";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

const METRICS = [
  // Shipment-based (require shipment history data)
  { key: "customer_volume_distribution", label: "Customer Distribution by Volume", group: "Shipment" },
  { key: "product_volume_pareto", label: "Product Volume Pareto Chart", group: "Shipment" },
  { key: "inbound_flow", label: "Inbound Flow by Location", group: "Shipment" },
  { key: "outbound_flow", label: "Outbound Flow by Location", group: "Shipment" },
  { key: "total_spending", label: "Total Spending by Vendor", group: "Shipment" },
  { key: "mode_split", label: "Transportation Mode Split", group: "Shipment" },
  // Master-data charts (available without shipment data)
  { key: "product_category_breakdown", label: "Product Count by Category", group: "Master Data" },
  { key: "customer_geographic_distribution", label: "Customer Distribution by State", group: "Master Data" },
  { key: "inventory_on_hand_by_location", label: "Inventory On-Hand by Location", group: "Master Data" },
];

function applyBlueTheme(figure: any) {
  if (!figure) return figure;
  const data = (figure.data || []).map((trace: any, i: number) => {
    const color = CHART_BLUE_SEQUENCE[i % CHART_BLUE_SEQUENCE.length];
    if (trace.type === "bar" || trace.type === "pie") {
      return { ...trace, marker: { ...(trace.marker || {}), color: trace.marker?.color || color } };
    }
    if (trace.type === "scatter") {
      return { ...trace, line: { ...(trace.line || {}), color: trace.line?.color || "#C1372B" } };
    }
    return trace;
  });
  return {
    ...figure,
    data,
    layout: {
      ...figure.layout,
      font: { family: "Inter, Roboto, sans-serif", color: "#0F1E3D" },
      paper_bgcolor: "#FFFFFF",
      plot_bgcolor: "#FFFFFF",
      colorway: CHART_BLUE_SEQUENCE,
    },
  };
}

function buildLineCoords(map: FlowMapResponse) {
  const nodeById = new Map(map.nodes.map((n) => [n.id, n]));
  const lon: Array<number | null> = [];
  const lat: Array<number | null> = [];

  map.lanes.forEach((l) => {
    const o = nodeById.get(l.origin);
    const d = nodeById.get(l.destination);
    if (!o || !d) return;
    if (o.lon === null || o.lat === null || d.lon === null || d.lat === null) return;
    lon.push(o.lon, d.lon, null);
    lat.push(o.lat, d.lat, null);
  });

  return { lon, lat };
}

export default function BusinessInsightsPage() {
  const { projectId, runId } = useProject();
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>("all");
  const [figures, setFigures] = React.useState<Record<string, any>>({});
  const [scopeSummary, setScopeSummary] = React.useState<Record<string, ScopeSummaryEntry> | null>(null);
  const [excludedRecords, setExcludedRecords] = React.useState<Record<string, any[]>>({});
  const [expandedExcluded, setExpandedExcluded] = React.useState<string | null>(null);

  const [inboundMap, setInboundMap] = React.useState<FlowMapResponse | null>(null);
  const [outboundMap, setOutboundMap] = React.useState<FlowMapResponse | null>(null);
  const [flowMapNote, setFlowMapNote] = React.useState<string | null>(null);
  const [flowMapTopN] = React.useState<number>(120);

  React.useEffect(() => {
    if (!runId) return;

    METRICS.forEach((m) => {
      getBusinessMetric(projectId, runId, m.key, statusFilter)
        .then((fig) => setFigures((prev) => ({ ...prev, [m.key]: applyBlueTheme(fig) })))
        .catch(() => setFigures((prev) => ({ ...prev, [m.key]: null })));
    });

    getScopeSummary(projectId, runId)
      .then((res) => setScopeSummary(res.datasets))
      .catch(() => setScopeSummary(null));

    // Geographic flow maps (origin → destination)
    Promise.all([
      getInboundFlowMap(projectId, runId, statusFilter, flowMapTopN, "volume"),
      getOutboundFlowMap(projectId, runId, statusFilter, flowMapTopN, "volume"),
    ])
      .then(([inb, outb]) => {
        setInboundMap(inb);
        setOutboundMap(outb);
        const notes = [inb.note, outb.note].filter(Boolean).join(" | ");
        setFlowMapNote(notes || null);
      })
      .catch(() => {
        setInboundMap(null);
        setOutboundMap(null);
        setFlowMapNote("Flow map data not available for this run.");
      });
  }, [projectId, runId, statusFilter, flowMapTopN]);

  async function handleExpandExcluded(dataset: string) {
    const next = expandedExcluded === dataset ? null : dataset;
    setExpandedExcluded(next);
    if (next && !excludedRecords[dataset] && runId) {
      try {
        const res = await getExcludedRecords(projectId, runId, dataset);
        setExcludedRecords((prev) => ({ ...prev, [dataset]: res.records }));
      } catch {
        setExcludedRecords((prev) => ({ ...prev, [dataset]: [] }));
      }
    }
  }

  const scopedDatasets = scopeSummary
    ? Object.entries(scopeSummary).filter(([, s]) => s.total > 0)
    : [];
  const totalExcluded = scopedDatasets.reduce((sum, [, s]) => sum + s.excluded, 0);

  return (
    <Box>
      <PageHeader
        title="Business Insights"
        subtitle="Sanity-check the data from a business perspective, filterable by validation status. Charts reflect Scope Filters — records outside business scope are excluded automatically."
      />
      <Box sx={{ mb: 3 }}>
        <StatusFilterToggle value={statusFilter} onChange={setStatusFilter} />
      </Box>

      {/* Geographic Flow Maps (Inbound / Outbound) */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 0.5 }}>
            Geographic Flow Maps (Origin → Destination)
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            These maps show real origin/destination lanes based on your run data and the available location addresses (auto‑geocoded when needed).
          </Typography>
          {flowMapNote && (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 2 }}>
              Note: {flowMapNote}
            </Typography>
          )}

          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <Paper variant="outlined" sx={{ p: 1.5 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1, color: "primary.main" }}>
                  Inbound Map (Origin → Facility)
                </Typography>
                {!inboundMap ? (
                  <Typography color="text.secondary" sx={{ py: 1.5, fontSize: 13 }}>
                    Loading...
                  </Typography>
                ) : inboundMap.note ? (
                  <Typography color="text.secondary" sx={{ py: 1.5, fontSize: 13 }}>
                    {inboundMap.note}
                  </Typography>
                ) : (
                  <Plot
                    data={[
                      {
                        type: "scattergeo",
                        mode: "lines",
                        ...buildLineCoords(inboundMap),
                        line: { width: 1, color: "rgba(91,155,213,0.65)" },
                        hoverinfo: "skip",
                      },
                      {
                        type: "scattergeo",
                        mode: "markers",
                        lon: inboundMap.nodes.map((n) => n.lon).filter((v): v is number => typeof v === "number"),
                        lat: inboundMap.nodes.map((n) => n.lat).filter((v): v is number => typeof v === "number"),
                        text: inboundMap.nodes.map((n) => n.name),
                        marker: { size: 6, color: "rgba(16,30,58,0.9)", line: { width: 1, color: "#5b9bd5" } },
                        hovertemplate: "%{text}<extra></extra>",
                      },
                    ]}
                    layout={{
                      autosize: true,
                      height: 360,
                      margin: { t: 10, b: 0, l: 0, r: 0 },
                      geo: {
                        scope: "world",
                        projection: { type: "natural earth" },
                        showland: true,
                        landcolor: "#F3F4F6",
                        showocean: true,
                        oceancolor: "#E7F1FF",
                        showcountries: true,
                        countrycolor: "rgba(0,0,0,0.12)",
                      },
                    }}
                    style={{ width: "100%" }}
                    useResizeHandler
                    config={{ displayModeBar: false }}
                  />
                )}
              </Paper>
            </Grid>

            <Grid item xs={12} md={6}>
              <Paper variant="outlined" sx={{ p: 1.5 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1, color: "primary.main" }}>
                  Outbound Map (Facility → Destination)
                </Typography>
                {!outboundMap ? (
                  <Typography color="text.secondary" sx={{ py: 1.5, fontSize: 13 }}>
                    Loading...
                  </Typography>
                ) : outboundMap.note ? (
                  <Typography color="text.secondary" sx={{ py: 1.5, fontSize: 13 }}>
                    {outboundMap.note}
                  </Typography>
                ) : (
                  <Plot
                    data={[
                      {
                        type: "scattergeo",
                        mode: "lines",
                        ...buildLineCoords(outboundMap),
                        line: { width: 1, color: "rgba(110,231,183,0.6)" },
                        hoverinfo: "skip",
                      },
                      {
                        type: "scattergeo",
                        mode: "markers",
                        lon: outboundMap.nodes.map((n) => n.lon).filter((v): v is number => typeof v === "number"),
                        lat: outboundMap.nodes.map((n) => n.lat).filter((v): v is number => typeof v === "number"),
                        text: outboundMap.nodes.map((n) => n.name),
                        marker: { size: 6, color: "rgba(16,30,58,0.9)", line: { width: 1, color: "#6ee7b7" } },
                        hovertemplate: "%{text}<extra></extra>",
                      },
                    ]}
                    layout={{
                      autosize: true,
                      height: 360,
                      margin: { t: 10, b: 0, l: 0, r: 0 },
                      geo: {
                        scope: "world",
                        projection: { type: "natural earth" },
                        showland: true,
                        landcolor: "#F3F4F6",
                        showocean: true,
                        oceancolor: "#E7F1FF",
                        showcountries: true,
                        countrycolor: "rgba(0,0,0,0.12)",
                      },
                    }}
                    style={{ width: "100%" }}
                    useResizeHandler
                    config={{ displayModeBar: false }}
                  />
                )}
              </Paper>
            </Grid>
          </Grid>

          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
            Showing up to {flowMapTopN} highest-volume lanes per map. Missing or ungeocodable endpoints are omitted.
          </Typography>
        </CardContent>
      </Card>

      {/* Included / Excluded (Scope) Summary */}
      {scopedDatasets.length > 0 && (
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 2 }}>
              <VisibilityOffIcon sx={{ color: "warning.main" }} />
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                Business Scope — Included vs. Excluded
              </Typography>
              {totalExcluded > 0 && (
                <Chip label={`${totalExcluded} records excluded across all datasets`} color="warning" size="small" sx={{ ml: "auto" }} />
              )}
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Records excluded by Scope Filters are never deleted — they remain in Gold for full auditability,
              but are excluded from the charts above. Configure rules on the Scope Filters page.
            </Typography>

            <Grid container spacing={2} sx={{ mb: 2 }}>
              {scopedDatasets.map(([dataset, s]) => (
                <Grid item xs={12} sm={6} md={4} key={dataset}>
                  <Paper variant="outlined" sx={{ p: 1.5 }}>
                    <Typography variant="caption" sx={{ fontWeight: 600, display: "block" }}>
                      {dataset.replace(/_/g, " ")}
                    </Typography>
                    <Box sx={{ display: "flex", gap: 1, mt: 0.5, flexWrap: "wrap" }}>
                      <Chip label={`In scope: ${s.included}`} color="success" size="small" />
                      <Chip label={`Excluded: ${s.excluded}`} color={s.excluded > 0 ? "warning" : "default"} size="small" />
                      {s.pct_excluded > 0 && <Chip label={`${s.pct_excluded}%`} size="small" variant="outlined" />}
                    </Box>
                  </Paper>
                </Grid>
              ))}
            </Grid>

            {scopedDatasets.filter(([, s]) => s.excluded > 0).map(([dataset, s]) => (
              <Accordion key={dataset} expanded={expandedExcluded === dataset} onChange={() => handleExpandExcluded(dataset)} sx={{ mb: 1 }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography sx={{ fontWeight: 600, flexGrow: 1 }}>{dataset.replace(/_/g, " ")} — Exclusion Reasons</Typography>
                  <Chip label={`${s.excluded} excluded`} size="small" color="warning" />
                </AccordionSummary>
                <AccordionDetails>
                  <TableContainer component={Paper} variant="outlined" sx={{ mb: 2 }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow sx={{ bgcolor: "#FFF8E1" }}>
                          <TableCell sx={{ fontWeight: 600 }}>Exclusion Reason</TableCell>
                          <TableCell sx={{ fontWeight: 600 }}>Record Count</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {Object.entries(s.reasons).map(([reason, count]) => (
                          <TableRow key={reason}>
                            <TableCell sx={{ fontSize: 13 }}>{reason}</TableCell>
                            <TableCell>
                              <Chip label={count} size="small" />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                  {excludedRecords[dataset] && excludedRecords[dataset].length > 0 && (
                    <>
                      <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: "block" }}>
                        Sample excluded records (showing up to 500):
                      </Typography>
                      <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 300 }}>
                        <Table size="small" stickyHeader>
                          <TableHead>
                            <TableRow>
                              {Object.keys(excludedRecords[dataset][0] || {}).slice(0, 6).map((col) => (
                                <TableCell key={col} sx={{ fontSize: 10, fontFamily: "monospace", bgcolor: "#F3F4F6" }}>{col}</TableCell>
                              ))}
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {excludedRecords[dataset].slice(0, 20).map((rec, i) => (
                              <TableRow key={i}>
                                {Object.values(rec).slice(0, 6).map((v: any, j) => (
                                  <TableCell key={j} sx={{ fontSize: 10, maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                    {v === null || v === undefined ? "—" : String(v)}
                                  </TableCell>
                                ))}
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </TableContainer>
                    </>
                  )}
                </AccordionDetails>
              </Accordion>
            ))}
          </CardContent>
        </Card>
      )}

      <Grid container spacing={3}>
        {METRICS.map((m) => (
          <Grid item xs={12} md={6} key={m.key}>
            <Card>
              <CardContent>
                <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600, color: "primary.main" }}>
                  {m.label}
                </Typography>
                {figures[m.key] === undefined ? (
                  <Typography color="text.secondary" sx={{ py: 2 }}>Loading...</Typography>
                ) : figures[m.key] === null || !figures[m.key]?.data?.length ? (
                  <Typography color="text.secondary" sx={{ py: 2, fontSize: 13 }}>
                    {m.group === "Shipment"
                      ? "No shipment data found for this run. Configure shipment_history, outbound_shipment_history, or inbound_shipment_history as a data source and re-run the pipeline."
                      : "No data found. Run the full pipeline (Phase 3) to populate this chart."}
                  </Typography>
                ) : (
                  <Plot
                    data={figures[m.key].data}
                    layout={{ ...figures[m.key].layout, autosize: true, height: 360, margin: { t: 20 } }}
                    style={{ width: "100%" }}
                    useResizeHandler
                    config={{ displayModeBar: false }}
                  />
                )}
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
