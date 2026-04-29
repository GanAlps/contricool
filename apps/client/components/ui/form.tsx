import { type ReactNode, createContext, useContext, useId } from 'react';
import {
  Controller,
  type ControllerProps,
  type FieldPath,
  type FieldValues,
  FormProvider,
  type UseFormReturn,
  useFormContext,
} from 'react-hook-form';
import { Text, View } from 'react-native';

import { cn } from '~/lib/utils';

import { Label } from './Label';

type FormFieldContext = {
  name: string;
  fieldId: string;
  messageId: string;
  hasError: boolean;
};

const FormFieldCtx = createContext<FormFieldContext | null>(null);

export function Form<T extends FieldValues>({
  form,
  children,
}: {
  form: UseFormReturn<T>;
  children: ReactNode;
}) {
  return <FormProvider {...form}>{children}</FormProvider>;
}

export function FormField<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
>(props: ControllerProps<TFieldValues, TName>) {
  const fieldId = useId();
  const messageId = `${fieldId}-message`;
  const { formState } = useFormContext<TFieldValues>();
  const errors = formState.errors as unknown as Record<string, unknown>;
  const hasError = Boolean(errors[props.name]);
  return (
    <FormFieldCtx.Provider value={{ name: props.name, fieldId, messageId, hasError }}>
      <Controller {...props} />
    </FormFieldCtx.Provider>
  );
}

function useFormFieldContext(): FormFieldContext {
  const ctx = useContext(FormFieldCtx);
  if (!ctx) {
    throw new Error('FormItem/FormControl/FormMessage must be used within a FormField');
  }
  return ctx;
}

export function FormItem({ children, className }: { children: ReactNode; className?: string }) {
  return <View className={cn('mb-4', className)}>{children}</View>;
}

export function FormLabel({ children, className }: { children: ReactNode; className?: string }) {
  const { fieldId } = useFormFieldContext();
  return (
    <Label htmlFor={fieldId} className={className}>
      {children}
    </Label>
  );
}

export function FormControl({ children }: { children: ReactNode }) {
  const { fieldId, messageId, hasError } = useFormFieldContext();
  // Inject the id and aria props onto the single child.
  if (typeof children === 'object' && children !== null && 'props' in children) {
    const child = children as { props: Record<string, unknown>; type?: unknown };
    const merged = {
      ...child.props,
      nativeID: fieldId,
      describedBy: messageId,
      invalid: hasError,
    } as Record<string, unknown>;
    // Re-create the element with merged props.
    const cloneElement =
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      (require('react') as typeof import('react')).cloneElement;
    return cloneElement(children as Parameters<typeof cloneElement>[0], merged);
  }
  return <>{children}</>;
}

export function FormMessage({ className }: { className?: string }) {
  const { name, messageId, hasError } = useFormFieldContext();
  const { formState } = useFormContext();
  const errors = formState.errors as unknown as Record<string, { message?: string } | undefined>;
  const msg = errors[name]?.message ?? null;
  if (!hasError || !msg) {
    return null;
  }
  return (
    <Text
      // RN-Web prefers `nativeID` → DOM `id`.
      nativeID={messageId}
      className={cn('mt-1 text-sm text-danger-600', className)}
      testID={`${name}-error`}
    >
      {msg}
    </Text>
  );
}
