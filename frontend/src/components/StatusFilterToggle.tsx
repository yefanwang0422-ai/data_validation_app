"use client";

import * as React from "react";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import type { StatusFilter } from "@/lib/api";

export default function StatusFilterToggle({
  value,
  onChange,
}: {
  value: StatusFilter;
  onChange: (value: StatusFilter) => void;
}) {
  return (
    <ToggleButtonGroup
      value={value}
      exclusive
      size="small"
      onChange={(_, v) => v && onChange(v)}
      sx={{
        bgcolor: "#fff",
        "& .MuiToggleButton-root": {
          textTransform: "none",
          fontWeight: 600,
          px: 2,
        },
        "& .Mui-selected": {
          bgcolor: "primary.main !important",
          color: "#fff !important",
        },
      }}
    >
      <ToggleButton value="all">All Records</ToggleButton>
      <ToggleButton value="validated">Validated Only</ToggleButton>
      <ToggleButton value="flagged">Flagged / Unresolved</ToggleButton>
    </ToggleButtonGroup>
  );
}
