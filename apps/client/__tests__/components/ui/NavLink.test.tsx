import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  getRouterMock,
  mockExpoRouter,
  resetRouterMock,
  setPathname,
} from '../../app/_router-mock';

mockExpoRouter();

import { NavLink } from '~/components/ui/NavLink';

describe('NavLink', () => {
  beforeEach(() => {
    resetRouterMock();
  });
  afterEach(() => {
    resetRouterMock();
  });

  it('renders without aria-current when pathname differs', () => {
    setPathname('/dashboard');
    render(
      <NavLink to="/friends" testID="nl">
        Friends
      </NavLink>,
    );
    expect(screen.getByTestId('nl').getAttribute('aria-current')).toBeNull();
  });

  it('renders aria-current="page" when pathname matches exactly', () => {
    setPathname('/friends');
    render(
      <NavLink to="/friends" testID="nl">
        Friends
      </NavLink>,
    );
    expect(screen.getByTestId('nl').getAttribute('aria-current')).toBe('page');
  });

  it('renders aria-current for a sub-route', () => {
    setPathname('/friends/abc123');
    render(
      <NavLink to="/friends" testID="nl">
        Friends
      </NavLink>,
    );
    expect(screen.getByTestId('nl').getAttribute('aria-current')).toBe('page');
  });

  it('navigates when pressed', () => {
    setPathname('/dashboard');
    render(
      <NavLink to="/friends" testID="nl">
        Friends
      </NavLink>,
    );
    fireEvent.click(screen.getByTestId('nl'));
    const calls = getRouterMock().calls;
    expect(calls).toEqual([{ kind: 'push', href: '/friends' }]);
  });
});
