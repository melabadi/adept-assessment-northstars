import type { RequestDetail } from '../../api/types';

export interface DetailPanelProps {
  detail: RequestDetail;
  /** Re-reads the request and its history after a successful change. */
  onChanged: () => Promise<void>;
  className?: string;
}
