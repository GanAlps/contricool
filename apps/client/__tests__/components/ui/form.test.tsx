import { zodResolver } from '@hookform/resolvers/zod';
import { fireEvent, render, screen } from '@testing-library/react';
import { useForm } from 'react-hook-form';
import { describe, expect, it, vi } from 'vitest';
import { z } from 'zod';

import { Button } from '~/components/ui/Button';
import { Input } from '~/components/ui/Input';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '~/components/ui/form';

const Schema = z.object({
  email: z.string().email('Invalid email'),
});
type FormValues = z.infer<typeof Schema>;

function Demo({ onSubmit }: { onSubmit: (v: FormValues) => void }) {
  const form = useForm<FormValues>({ resolver: zodResolver(Schema), defaultValues: { email: '' } });
  return (
    <Form form={form}>
      <FormField
        control={form.control}
        name="email"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Email</FormLabel>
            <FormControl>
              <Input testID="email" value={field.value} onChangeText={field.onChange} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <Button testID="submit" onPress={form.handleSubmit(onSubmit)}>
        Submit
      </Button>
    </Form>
  );
}

describe('Form / FormField / FormControl / FormMessage', () => {
  it('shows the field error linked via aria-describedby on invalid submit', async () => {
    const submitted = vi.fn();
    render(<Demo onSubmit={submitted} />);
    fireEvent.click(screen.getByTestId('submit'));
    const err = await screen.findByTestId('email-error');
    expect(err).toHaveTextContent('Invalid email');
    const input = screen.getByTestId('email');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    const describedBy = input.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(err).toHaveAttribute('id', describedBy as string);
    expect(submitted).not.toHaveBeenCalled();
  });

  it('submits when valid', async () => {
    const submitted = vi.fn();
    render(<Demo onSubmit={submitted} />);
    fireEvent.change(screen.getByTestId('email'), {
      target: { value: 'a@b.com' },
    });
    fireEvent.click(screen.getByTestId('submit'));
    await screen.findByTestId('submit');
    // Wait a tick for async resolver.
    await new Promise((r) => setTimeout(r, 10));
    expect(submitted).toHaveBeenCalledOnce();
    expect(submitted).toHaveBeenCalledWith(
      expect.objectContaining({ email: 'a@b.com' }),
      expect.anything(),
    );
  });
});
