// jest-expo: expo-* native modullarining mocklari shu preset ichida;
// transformIgnorePatterns ham presetdan (expo*, react-native*, standard-navigation...).
// Serverda 4 CPU / 3 GB RAM - shuning uchun `npm test` --maxWorkers=2 bilan yuradi.
module.exports = {
  preset: 'jest-expo/android',
  setupFiles: ['<rootDir>/jest.setup.js'],
  testMatch: ['<rootDir>/__tests__/**/*.test.ts?(x)', '<rootDir>/src/**/*.test.ts?(x)'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  clearMocks: true,
};
