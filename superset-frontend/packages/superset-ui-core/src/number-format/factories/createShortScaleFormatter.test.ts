/* ... header Apache License ... */

import {
    NumberFormatter,
    NumberFormatterRegistry,
    createShortScaleFormatter,
  } from '@superset-ui/core';
  
  describe('createShortScaleFormatter', () => {
    it('creates an instance of NumberFormatter', () => {
      expect(createShortScaleFormatter({ formatString: '.1k' })).toBeInstanceOf(
        NumberFormatter,
      );
    });
  
    it('formats with fixed decimals and k/M/B/T suffix', () => {
      const f = createShortScaleFormatter({ formatString: '.1k' });
      expect(f(523)).toBe('523.0');
      expect(f(1234)).toBe('1.2k');
      expect(f(12345)).toBe('12.3k');
      expect(f(99999)).toBe('100.0k');
      expect(f(123456)).toBe('123.5k');
      expect(f(1234567)).toBe('1.2M');
      expect(f(2.5e9)).toBe('2.5B');
      expect(f(7.7e12)).toBe('7.7T');
    });
  
    it('rolls over to the next unit when rounding reaches 1000', () => {
      const f = createShortScaleFormatter({ formatString: '.1k' });
      expect(f(999950)).toBe('1.0M');
    });
  
    it('supports 2 decimals, trimming (~) and explicit sign (+)', () => {
      expect(createShortScaleFormatter({ formatString: '.2k' })(123456)).toBe(
        '123.46k',
      );
      expect(createShortScaleFormatter({ formatString: '.1~k' })(120000)).toBe(
        '120k',
      );
      expect(createShortScaleFormatter({ formatString: '+.1k' })(1500)).toBe(
        '+1.5k',
      );
    });
  
    it('is picked up by the registry for free-form format strings', () => {
      const registry = new NumberFormatterRegistry();
      expect(registry.format('.1k', 123456)).toBe('123.5k');
      expect(registry.format('.3s', 123456)).toBe('123k'); // unchanged behaviour
    });
  });