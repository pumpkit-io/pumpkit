import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';
import { useAccount } from '@/features/account/useAccount';
import { useBilling } from '@/features/billing/useBilling';
import { useInstance } from '@/features/instance/useInstance';
import { Topbar } from '@/features/topbar/Topbar';

/**
 * Rendered inside AppLayout. Until the Settings cards land it opens the Account and Billing
 * dialogs the user menu opens, so the sidebar's Settings row leads somewhere real.
 */
export function Settings() {
  const { logout } = useAuth();
  const account = useAccount();
  const billing = useBilling();
  const { sells_plans } = useInstance();

  return (
    <>
      <Topbar
        title="Settings"
        actions={
          <Button variant="outline" size="sm" className="h-9" onClick={() => void logout()}>
            Sign out
          </Button>
        }
      />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-3 px-4 py-8 sm:flex-row sm:px-6">
          <Button variant="outline" className="h-10" onClick={() => account.open()}>
            Account
          </Button>
          {sells_plans && (
            <Button variant="outline" className="h-10" onClick={() => billing.open('settings')}>
              Billing
            </Button>
          )}
        </div>
      </div>
    </>
  );
}
