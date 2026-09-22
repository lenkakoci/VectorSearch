import defaultTheme from 'tailwindcss/defaultTheme'

// Colours taken from cgs.gov.cz: navy and blue for structure, the green as a
// sparing accent, and the pale tints of a geological map for labels. Each
// colour carries one meaning across the whole page (see src/lib/tone.ts), so
// green is never both "found by both methods" and "verified".
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Roboto', ...defaultTheme.fontFamily.sans],
      },
      colors: {
        // Neutral grey of the CGS site (#3b3b3b text, #ededed and #f7f7f7 grounds)
        // instead of Tailwind's blue-tinted slate.
        slate: {
          50: '#f7f7f7',
          100: '#ededed',
          200: '#dfdfdf',
          300: '#c9c9c9',
          400: '#9b9b9b',
          500: '#6c6c6c',
          600: '#555555',
          700: '#3b3b3b',
          800: '#2c2c2c',
          900: '#1f1f1f',
          950: '#141414',
        },
        brand: {
          50: '#eef4fa',
          100: '#dae7f4',
          200: '#b6cfe7',
          300: '#86afd6',
          400: '#4a8cc6',
          500: '#0779bf',
          600: '#005a9c',
          700: '#003975',
          800: '#002d5d',
          900: '#002042',
          950: '#00152c',
        },
        leaf: {
          50: '#f3f8ee',
          100: '#e3efd9',
          200: '#c9e1bd',
          300: '#a7d06d',
          400: '#90c72f',
          500: '#7fc100',
          600: '#619500',
          700: '#4b7300',
          800: '#3b5a08',
          900: '#2f470d',
        },
        sand: {
          50: '#fdf8ee',
          100: '#faeed5',
          200: '#f4daa6',
          300: '#ecc477',
          400: '#dfa84a',
          500: '#c98b2c',
          600: '#a86e20',
          700: '#85541c',
          800: '#6b441c',
          900: '#58391a',
        },
        clay: {
          50: '#fdf2ef',
          100: '#fbe3dc',
          200: '#f9c9bf',
          300: '#f2a595',
          400: '#e67c66',
          500: '#d65b43',
          600: '#b94531',
          700: '#9a3829',
          800: '#7e3026',
          900: '#682b24',
        },
      },
    },
  },
  plugins: [],
}
