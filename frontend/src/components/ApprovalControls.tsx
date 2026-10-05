import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, Ban } from "lucide-react";
import { useId, useState } from "react";
import { errorMessage } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { ApprovalDetail } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { humanize } from "../lib/format";
import { RiskBadge } from "./badges";
import { Modal } from "./Modal";
import { useToast } from "./Toast";
import { Button, Field, JsonBlock, Notice, inputClass } from "./ui";

const APPROVE_REASONS = [
  ["EVIDENCE_SUFFICIENT", "Evidence is sufficient"],
  ["APPROVED_WITH_MONITORING", "Approved with additional monitoring"],
] as const;
const REJECT_REASONS = [
  ["INSUFFICIENT_EVIDENCE", "Insufficient evidence"],
  ["RISK_TOO_HIGH", "Risk too high"],
  ["CHANGE_FREEZE", "Change freeze in effect"],
  ["ALTERNATIVE_PREFERRED", "Alternative preferred"],
  ["OTHER", "Other (explain in comment)"],
] as const;
const CANCEL_REASONS = [
  ["NO_LONGER_NEEDED", "No longer needed"],
  ["PLAN_CHANGED", "Plan changed"],
  ["OTHER", "Other (explain in comment)"],
] as const;

type Mode = "approve" | "reject" | "cancel" | null;

function invalidateAll(queryClient: ReturnType<typeof useQueryClient>) {
  for (const key of ["approvals", "approval", "investigation", "investigations", "actions", "dashboard", "incident", "incidents"]) {
    void queryClient.invalidateQueries({ queryKey: [key] });
  }
}

export function ApprovalControls({ approval }: { approval: ApprovalDetail }) {
  const { can, user } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [mode, setMode] = useState<Mode>(null);
  const [reason, setReason] = useState<string>("");
  const [comment, setComment] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const formId = useId();

  const open = (next: Mode) => {
    setMode(next);
    setReason(next === "approve" ? APPROVE_REASONS[0][0] : next === "reject" ? REJECT_REASONS[0][0] : CANCEL_REASONS[0][0]);
    setComment("");
    setConfirmed(false);
  };

  const mutation = useMutation({
    mutationFn: async () => {
      if (mode === "approve") return endpoints.approve(approval.id, reason, comment);
      if (mode === "reject") return endpoints.reject(approval.id, reason, comment);
      return endpoints.cancelApproval(approval.id, reason, comment);
    },
    onSuccess: (result) => {
      const verb = mode === "approve" ? "Approved" : mode === "reject" ? "Rejected" : "Cancelled";
      toast(`${verb} ${result.action?.tool_name ?? "action"}${result.investigation_resumed ? " — investigation resumed." : "."}`, "success");
      setMode(null);
      invalidateAll(queryClient);
    },
    onError: (error) => {
      toast(errorMessage(error), "error");
      invalidateAll(queryClient);
    },
  });

  if (approval.status !== "pending") return null;

  const isRequester = approval.requested_by === user?.username;
  const canCancel = (isRequester && can("approvals:cancel")) || can("approvals:decide");
  const decideBlocked = !can("approvals:decide") ? `Your role (${humanize(user?.role)}) cannot decide approvals.` : null;
  const commentRequired = reason === "OTHER" && comment.trim().length < 3;
  const action = approval.action;

  return (
    <div className="flex flex-wrap items-start gap-2">
      <Button
        variant="success"
        icon={<CircleCheck className="size-4" aria-hidden />}
        onClick={() => open("approve")}
        disabledReason={decideBlocked ?? (approval.can_approve ? null : approval.approve_block_reason)}
      >
        Approve…
      </Button>
      <Button
        variant="danger"
        icon={<CircleX className="size-4" aria-hidden />}
        onClick={() => open("reject")}
        disabledReason={decideBlocked ?? (approval.can_reject ? null : approval.reject_block_reason)}
      >
        Reject…
      </Button>
      <Button
        variant="secondary"
        icon={<Ban className="size-4" aria-hidden />}
        onClick={() => open("cancel")}
        disabledReason={canCancel ? null : "Only the requester or an approver can cancel this request."}
      >
        Cancel request
      </Button>

      <Modal
        open={mode !== null}
        onClose={() => !mutation.isPending && setMode(null)}
        title={mode === "approve" ? "Approve simulated action" : mode === "reject" ? "Reject simulated action" : "Cancel approval request"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setMode(null)} disabled={mutation.isPending}>Back</Button>
            <Button
              type="submit"
              form={formId}
              variant={mode === "approve" ? "success" : mode === "reject" ? "danger" : "primary"}
              loading={mutation.isPending}
              disabledReason={
                mode === "approve" && !confirmed ? "Tick the confirmation box to enable approval." : commentRequired ? "A comment is required for 'Other'." : null
              }
            >
              {mode === "approve" ? "Confirm approval" : mode === "reject" ? "Confirm rejection" : "Cancel request"}
            </Button>
          </>
        }
      >
        <form
          id={formId}
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if ((mode === "approve" && !confirmed) || commentRequired) return;
            mutation.mutate();
          }}
        >
          {action && (
            <div className="space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <code className="font-mono text-sm font-semibold text-slate-900">{action.tool_name}</code>
                <RiskBadge value={approval.risk_level} />
                <span className="text-xs text-slate-500">target: {approval.target_resource}</span>
              </div>
              {action.policy_decision && <p className="text-xs text-slate-600">{action.policy_decision.explanation}</p>}
              <details>
                <summary className="cursor-pointer text-xs font-medium text-navy-700">Parameters (validated by the tool registry)</summary>
                <div className="mt-2"><JsonBlock value={action.parameters} label="Action parameters" /></div>
              </details>
              <p className="font-mono text-[11px] text-slate-500">Action hash: {approval.action_hash.slice(0, 24)}… (any plan change invalidates this approval)</p>
            </div>
          )}
          {mode === "approve" && (
            <Notice tone="warning" title="Simulated remediation">
              Approval lets the workflow execute this action against seeded demo state only. The policy engine re-checks the
              approval scope, expiry and action hash immediately before execution.
            </Notice>
          )}
          <Field label="Reason code" htmlFor={`${formId}-reason`}>
            <select id={`${formId}-reason`} className={inputClass} value={reason} onChange={(event) => setReason(event.target.value)}>
              {(mode === "approve" ? APPROVE_REASONS : mode === "reject" ? REJECT_REASONS : CANCEL_REASONS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </Field>
          <Field label="Comment (optional, recorded in the audit log)" htmlFor={`${formId}-comment`}>
            <textarea id={`${formId}-comment`} className={inputClass} rows={3} maxLength={1000} value={comment} onChange={(event) => setComment(event.target.value)} />
          </Field>
          {mode === "approve" && (
            <label className="flex items-start gap-2 text-sm text-slate-800">
              <input type="checkbox" className="mt-1 size-4" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
              <span>I have reviewed the evidence and policy decision and explicitly approve this <strong>simulated</strong> action.</span>
            </label>
          )}
        </form>
      </Modal>
    </div>
  );
}
