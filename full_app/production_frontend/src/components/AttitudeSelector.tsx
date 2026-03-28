import { Smile, Angry } from "lucide-react";
import { Label } from "./ui/label";
import { Button } from "./ui/button";

interface AttitudeSelectorProps {
  value: "nice" | "mean";
  onChange: (value: "nice" | "mean") => void;
  disabled?: boolean;
}

export function AttitudeSelector({
  value,
  onChange,
  disabled,
}: AttitudeSelectorProps) {
  return (
    <div className="space-y-2">
      <Label>Editing Attitude</Label>
      <div className="grid grid-cols-2 gap-3">
        <Button
          type="button"
          variant={value === "nice" ? "default" : "outline"}
          className={`h-12 text-base ${value === "nice" ? "bg-green-600 hover:bg-green-700 text-white border-green-600" : ""}`}
          onClick={() => onChange("nice")}
          disabled={disabled}
        >
          <Smile className="w-5 h-5 mr-1" />
          Nice
        </Button>

        <Button
          type="button"
          variant={value === "mean" ? "default" : "outline"}
          className={`h-12 text-base ${value === "mean" ? "bg-red-600 hover:bg-red-700 text-white border-red-600" : ""}`}
          onClick={() => onChange("mean")}
          disabled={disabled}
        >
          <Angry className="w-5 h-5 mr-1" />
          Mean
        </Button>
      </div>
    </div>
  );
}
