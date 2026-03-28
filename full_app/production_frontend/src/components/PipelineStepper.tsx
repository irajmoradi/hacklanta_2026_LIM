import { Upload, Scissors, Wand2, Clapperboard, CheckCircle2, Loader2 } from "lucide-react";

interface PipelineStepperProps {
  completedSteps: number; // 0-4
  activeStep: number;     // which step is current (0-3)
  isProcessing: boolean;
  isDone: boolean;
}

const STEPS = [
  { label: "Upload", icon: Upload },
  { label: "Analyze", icon: Scissors },
  { label: "Plan", icon: Wand2 },
  { label: "Render", icon: Clapperboard },
];

export function PipelineStepper({
  completedSteps,
  activeStep,
  isProcessing,
  isDone,
}: PipelineStepperProps) {
  return (
    <div className="bg-card/80 backdrop-blur-sm border border-border rounded-2xl p-4 sm:p-5 shadow-lg shadow-black/10">
      <div className="flex items-center">
        {STEPS.map((step, i) => {
          const Icon = step.icon;
          const isCompleted = i < completedSteps || isDone;
          const isActive = i === activeStep && isProcessing;
          const isCurrent = i === completedSteps && !isProcessing && !isDone;

          return (
            <div key={step.label} className="flex items-center flex-1 last:flex-none">
              <div className="flex flex-col items-center gap-1.5">
                <div
                  className={`
                    flex items-center justify-center w-10 h-10 rounded-full transition-all duration-300
                    ${isCompleted ? "bg-green-600 text-white shadow-lg shadow-green-600/25" : ""}
                    ${isActive ? "bg-purple-600 text-white shadow-lg shadow-purple-600/30 ring-4 ring-purple-600/20" : ""}
                    ${isCurrent ? "bg-purple-600/20 text-purple-400 border-2 border-purple-500/50" : ""}
                    ${!isCompleted && !isActive && !isCurrent ? "bg-muted text-muted-foreground" : ""}
                  `}
                >
                  {isCompleted ? (
                    <CheckCircle2 className="w-5 h-5" />
                  ) : isActive ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <Icon className="w-5 h-5" />
                  )}
                </div>
                <span
                  className={`text-xs font-medium transition-colors ${
                    isCompleted || isActive || isCurrent
                      ? "text-foreground"
                      : "text-muted-foreground"
                  }`}
                >
                  {step.label}
                </span>
              </div>

              {i < STEPS.length - 1 && (
                <div className="flex-1 mx-2 sm:mx-3 mb-5">
                  <div className="h-0.5 rounded-full overflow-hidden bg-muted">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        i < completedSteps || isDone
                          ? "w-full bg-green-600"
                          : i === completedSteps && isProcessing
                            ? "w-1/2 bg-purple-600 animate-pulse"
                            : "w-0"
                      }`}
                    />
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
