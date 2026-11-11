import React from 'react';
import { UsersRound } from 'lucide-react';
import { ActionButton } from './ActionButton';

/** Presentation navigation only; this never grants an application role. */
export const DemoUserSwitch: React.FC<{ onClick: () => void }> = ({ onClick }) => <ActionButton
  label="Switch demo user" icon={<UsersRound />}
  aria-label="Switch demo user"
  title="Return to the mock reviewer / reporter picker"
  onClick={onClick}
/>;
