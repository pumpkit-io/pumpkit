import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { CreditCard, LogOut, Palette, User as UserIcon } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useAuth } from '@/contexts/AuthContext';
import { useAccount } from '@/features/account/useAccount';
import { useBilling } from '@/features/billing/useBilling';
import { useTheme, type ThemeChoice } from '@/features/theme/useTheme';
import { track } from '@/lib/analytics';

export function UserMenu({ trigger }: { trigger: ReactNode }) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const account = useAccount();
  const billing = useBilling();
  const { choice, setChoice } = useTheme();

  return (
    <DropdownMenu onOpenChange={(open) => open && track('sidebar_user_menu_opened')}>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="end" className="w-48">
        <DropdownMenuItem onSelect={() => { track('user_menu_account_clicked'); account.open(); }}>
          <UserIcon className="h-3.5 w-3.5" /> Account
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => { track('user_menu_billing_clicked'); billing.open('user_menu'); }}>
          <CreditCard className="h-3.5 w-3.5" /> Billing
        </DropdownMenuItem>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <Palette className="mr-2 h-3.5 w-3.5" /> Theme
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuRadioGroup
              value={choice}
              onValueChange={(next) => {
                track('user_menu_theme_changed', { theme: next });
                setChoice(next as ThemeChoice);
              }}
            >
              <DropdownMenuRadioItem value="system">System</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="light">Light</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="dark">Dark</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={async () => {
            track('user_menu_logout_clicked');
            await logout();
            navigate('/');
          }}
        >
          <LogOut className="h-3.5 w-3.5" /> Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
